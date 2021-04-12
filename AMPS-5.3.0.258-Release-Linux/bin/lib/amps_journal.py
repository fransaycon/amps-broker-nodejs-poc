###############################################################################
##
## Copyright (c) 2012-2019 60East Technologies Inc., All Rights Reserved.
##
## This computer software is owned by 60East Technologies Inc. and is
## protected by U.S. copyright laws and other laws and by international
## treaties.  This computer software is furnished by 60East Technologies
## Inc. pursuant to a written license agreement and may be used, copied,
## transmitted, and stored only in accordance with the terms of such
## license agreement and with the inclusion of the above copyright notice.
## This computer software or any other copies thereof may not be provided
## or otherwise made available to any other person.
##
## U.S. Government Restricted Rights.  This computer software: (a) was
## developed at private expense and is in all respects the proprietary
## information of 60East Technologies Inc.; (b) was not developed with
## government funds; (c) is a trade secret of 60East Technologies Inc.
## for all purposes of the Freedom of Information Act; and (d) is a
## commercial item and thus, pursuant to Section 12.212 of the Federal
## Acquisition Regulations (FAR) and DFAR Supplement Section 227.7202,
## Government's use, duplication or disclosure of the computer software
## is subject to the restrictions set forth by 60East Technologies Inc..
##
###############################################################################
"""module amps_journal

amps_journal provides easy access to AMPS journal files. Journal files
are opened using the `open_file' function, and then accessed using the
returned file-like object. Other functions provide shortcuts to common
operations.

FUNCTIONS:
dump(file, limit, is_localtime, is_extents, omit_data) dumps the contents of a journal file to stdout.
version(file) returns the version of a journal file.
upgrade(old_file, new_file) upgrades from an older journal file version to
 the latest.
open_file(path, mode, record_size) opens a journal file for reading or
 writing.

CLASSES:
File is the class for journal file reading.
Writer provides file writing.
Record represents a record from a journal file.

VERSIONS:

Version 1 has 96 byte header
Version 2,3 have 104 byte header

Version 3 adds replication path len to txn header using 'reserved'
bytes in header and the replication path bytes is placed just after
the authid and before the data. the txn record data will start at
sizeof(header) + topic.len + authId.len + replicationPath.len

Version 4 has write offset of 4096 and adds 'noop' txn's

Version 5 replaced sowKey with sowExpiration and flags with previousSize

"""
from __future__ import absolute_import
from __future__ import print_function
import amps_common
import glob
import gzip
import os
import shutil
import struct
import subprocess
import sys
import time
import hashlib

def internal_debug(str):
    pass
    #sys.stderr.write("amps_journal: %s\n" % str)
    #sys.stderr.flush()


LATEST_VERSION   = "amps::txlog/v8"
COMPRESSION_TYPE = "gz"

WRITER_VERSION             = 8
WRITER_VERSION_STRING      = LATEST_VERSION.ljust(32,'\0')
WRITER_COMPRESSION_TYPE    = COMPRESSION_TYPE.ljust(8,'\0')
WRITER_COMPRESSION_OPTIONS = 9;
AMPS_METADATA_SIZE         = 512
AMPS_TX_HEADER_SIZE        = 120
AMPS_MIN_TX_SIZE           = 256
AMPS_MIN_TX_SIZE_MASK      = AMPS_MIN_TX_SIZE - 1
AMPS_TX_OFFSET             = 4096
IS_LOCALTIME = False
IS_SOW_EXPIRATION_ISO = False
IS_SOW_EXPIRATION_LOCALTIME = False
OMIT_DATA    = False
DUMMY_DATA   = '<removed from dump>'

#
# a few functions for doing simple tasks ... these should be incorported into classes whenever we break Dump into more focused classes
#
def warn_active_journal():
   print("\n*****************************************************")
   print("NOTE: This is the active journal, and may change during\n" + \
         "the dump process. Extents may not be fully written, and\n" + \
         "reported counts and actual counts may differ.")
   print("*****************************************************\n")
    
def dump(file, start, stop, is_localtime, is_extents, omit_data=False, is_journal_extents=False, is_sow_expiration_iso=False):
   """Dumps the requested journal file to stdout.
   :param file: the path to the file to dump
   :type file: str
   :param start: the starting entry (starting from 0) to dump
   :type start: int
   :param stop: the ending entry (starting from 0) to dump
   :type stop: int
   :param is_localtime: whether to produce timestamps in the local timezone
   :type is_localtime: bool
   :param is_extents: whether to produce information on local and remote journal extents
   :type is_extents: bool
   :param omit_data: whether to suppress message data in the output
   :type omit_data: bool"""
   global IS_LOCALTIME
   global IS_SOW_EXPIRATION_ISO
   global OMIT_DATA
   global AMPS_MIN_TX_SIZE
   IS_LOCALTIME = is_localtime
   IS_SOW_EXPIRATION_ISO = is_sow_expiration_iso
   OMIT_DATA = omit_data
   total_entry_count = 0
   total_byte_count = 0
   total_remaining_count = 0
   total_unknown_message_type_count = 0
   total_unknown_command_count = 0
   source_extents_count = 0
   total_journal_size_count = 0
   extents = 0
   active_journal = False
   if (is_journal_extents):
       for jnl_path in Fileset(file).files():
           jnl_file = open_file(jnl_path, 'r')
           print(jnl_file.format_extents(True))
           local_extents = jnl_file.getExtents()
           if (local_extents[1] != 0 and local_extents[2] == 0):
               warn_active_journal()
       return

   for jnl_path in Fileset(file).files():
      jnl_file = open_file(jnl_path, 'r')
      print(jnl_file)
          
      jnl_file_byte_count = 0
      for record in jnl_file.records():
         if not record["typeStr"] == 'noop':
             if total_entry_count >= start and (stop is None or total_entry_count <= stop):
                 record['entryCount'] = total_entry_count
                 print(record)
                 total_entry_count += 1
                 jnl_file_byte_count = record['offset'] + record['size']
             if record['typeStr'] == 'unknown':
                 total_unknown_command_count += 1
             # We only know message type names up to 5 chars so far
             # and unknowns are '[hashvalue] (unknown)'
             if len(record['messageTypeName']) > 10:
                 total_unknown_command_count += 1
      total_byte_count += jnl_file_byte_count #(jnl_file_byte_count + AMPS_TX_OFFSET)
      total_journal_size_count += jnl_file.fileSize
      total_remaining_count = total_journal_size_count - total_byte_count
      if total_entry_count:
          extents = jnl_file.getExtents()
          if record['localTxId'] > extents[2]:
              active_journal = True

      if not is_extents:
         continue

      source_extents = jnl_file.getSourceExtents()
      source_extents_count = len(source_extents)
      if source_extents_count:
         print("Replication Source Info:")
         for k,v in source_extents.items():
            source = os.path.split(v[0])[1]
            print("Replication Source %s: %d" % (source,k))

         print("\nReplication Extents Info:")
         max_source_len = 0
         for k,v in source_extents.items():
            source = os.path.split(v[0])[1]
            if len(source) > max_source_len:
               max_source_len = len(source)

         local_extents = jnl_file.getExtents()
         local_pad = ' '*(max_source_len+2)
         print("Local Extents: {0}[{1}:{2}]".format(local_pad,local_extents[0],local_extents[2]))

         if len(source_extents):
            for k,v in source_extents.items():
               source = os.path.split(v[0])[1]
               pad = ' '*(max_source_len - len(source))
               print("Source {0} Extents: {1}[{2}:{3}]".format(source,pad,v[1],v[2]))
   if source_extents_count > 0:
      print("_____________________________________________________")
   if active_journal:
       warn_active_journal()
   print("""Total Entries    : {0}
Total Bytes      : {1}
Remaining Bytes  : {2}""".format(total_entry_count, total_byte_count, total_remaining_count))
   if total_unknown_command_count > 0:
      print('WARNING: %d messages with unknown command type.'%total_unknown_command_count)
   if total_unknown_message_type_count > 0:
      print('WARNING: %d messages with unknown message type.'%total_unknown_message_type_count)


def version(file):
   """Returns the version of the journal file.
   :param file: the full path to the journal file
   :type file: string
   :returns: string
   """
   f = open_file(file, 'r')
   return f.getVersionString()


def is_up_to_date(file, print_debug_info_to=None):
   if print_debug_info_to is not None:
      print_debug_info_to.write("version(%s)=%s\n" % (file, version(file)))
      print_debug_info_to.write("LATEST_VERSION=%s\n" % LATEST_VERSION)
      print_debug_info_to.write("is_up_to_date(%s) returning %s\n" % (file, version(file)))
      print_debug_info_to.flush()
   return  version(file) == LATEST_VERSION


def _stderr(msg):
    sys.stderr.write("%s\n" % msg)
    sys.stderr.flush()


def _compress(from_file, to_file):
    f_in = open(from_file, 'rb')
    try:
        f_out = gzip.open(to_file, 'wb')
        try:
            f_out.writelines(f_in)
        finally:
            f_out.close()
    finally:
        f_in.close()


def _decompress(from_file, to_file):
    f_in = gzip.open(from_file, 'rb')
    try:
        f_out = open(to_file, 'wb')
        try:
            f_out.writelines(f_in)
        finally:
            f_out.close()
    finally:
        f_in.close()


def _exec(args, cwd):
    if not os.path.exists(cwd):
        raise Exception("cwd '%s' does not exist: for command '%s'" % (cwd, " ".join(args)))
    p = subprocess.Popen(args,
                         cwd=cwd,
                         bufsize=-1,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    (out, err) = p.communicate()
    return (p.wait(), out, err)


def _exec_or_raise(args, cwd=os.getcwd()):
    (exit_code, stdout, stderr) = _exec(args, cwd=cwd)
    if exit_code != 0:
        err = [
            "exec failed with exit code=%s" % exit_code,
            "stdout: %s" % stdout,
            "stderr: %s" % stderr,
            "args: %s" % args,
            "cwd: %s" % cwd,
            ]
        raise Exception("\n".join(err))
    return (stdout, stderr)


def _upgrade_compressed(old_file, new_file):
    # strip the extension
    decompressed_old_file = old_file[0:old_file.rfind(".")]
    _decompress(old_file, decompressed_old_file)
    if new_file.endswith(".%s" % COMPRESSION_TYPE):
        # strip the extension
        decompressed_new_file = new_file[0:new_file.rfind(".")]
        _upgrade_uncompressed(decompressed_old_file,
                              decompressed_new_file)
        _compress(decompressed_new_file,
                  new_file)
        os.remove(decompressed_new_file)
    else:
        _upgrade_uncompressed(decompressed_old_file, new_file)
    os.remove(decompressed_old_file)


def _upgrade_uncompressed(old_file, new_file):
    infile = open_file(old_file, 'r')
    outfile = open_file(new_file, 'w', infile.getInstanceId(), infile.getExtents())
    for record in infile.records():
        outfile.write(record)
    outfile.close()


def upgrade(old_file, new_file):
   """Upgrades a journal file to the newest version.

   :param old_file: the full path to the old journal file.
   :param new_file: the full path to the new journal file.
   """
   d = Fileset([old_file])
   for filename in d.files():
     if filename.endswith(COMPRESSION_TYPE):
         _upgrade_compressed(filename, new_file)
     else:
         _upgrade_uncompressed(filename, new_file)


def open_file(path, mode='r', instanceId=None, extents=None):
   """Opens a journal file at the given path and returns a journal file object.

   :param path: the full path to the given journal file.
   :param mode: `r' to read the file, `w' to write, defaults to 'r'.
   :param instanceId: the name of the AMPS instance this journal is intended for. Required when writing.
   :param extents: a tuple containing the beginning and ending tx id to be written into this journal. Required when writing.
   :returns: a :class:File instanceor :class:Writer instance, depending on the chosen `mode'.
   """
   valid_modes = ['r', 'w']
   if mode is None or not mode in valid_modes:
      raise RuntimeError("unknown mode: '%s'" % mode)
   elif mode == 'w'and  (instanceId is None or extents is None):
      raise RuntimeError("must supply instanceId and extents when writing a journal file.")
   elif mode == 'r':
      return File(path)
   elif mode == 'w':
      return Writer(path, instanceId, extents)


#
# end functions
#
class Fileset:
   """
   A fancy wrapper around glob. Pass in a list of file globs and it will glob them and
   allow iteration via the files method."""
   def __init__(self, filenames):
      # Let's fixup filenames if needed
      self._filenames = []
      for filename in filenames:
         self._filenames = self._filenames + glob.glob(filename)

      if(len(self._filenames) == 0):
         raise RuntimeError("\nError: no files matching '%s' found.\n" % "' or '".join(filenames))
   def files(self):
      return self._filenames


class Record(dict):
   """A dictionary with overridden __str__."""
   def __init__(self, properties):
      self.update(properties)
   def __str__(self):
      if self['version'] >= 7:
         formatstr = """Entry               : {entryCount:30}
CRC                 : {crc:30}
type                : {typeStr:>30}
flags               : {flagsStr:>30}
offset              : {offset:30}
entry size          : {size:30}
msg len             : {messageLen:30}
msg type            : {messageTypeName:>30}
localTxId           : {localTxId:30}
previousLocalTxId   : {previousLocalTxId:30}
sourceTxId          : {sourceTxId:30}
source              : {sourceNameHash:30}
client              : {clientNameHash:30}
clientSeq           : {clientSeq:30}
topicHash           : {topicHash:30}
SOW expiration      : {sowExpiration:>30}
iso8601 timestamp   : {isoTimestamp:>30}
timestamp           : {timestamp:30}
previous size       : {previousSize:30}
topic len           : {topicLen:30}
topic               : [{topic}]
data                : [{data}]"""
         if self["typeStr"] == "transfer":
            formatstr += """
owner               : {owner:30}
requestPath         : [{requestPath}]"""
      elif self['version'] >= 6:
         formatstr = """Entry               : {entryCount:30}
CRC                 : {crc:30}
type                : {typeStr:>30}
entry size          : {size:30}
msg len             : {messageLen:30}
msg type            : {messageTypeName:>30}
localTxId           : {localTxId:30}
previousLocalTxId   : {previousLocalTxId:30}
sourceTxId          : {sourceTxId:30}
source              : {sourceNameHash:30}
client              : {clientNameHash:30}
clientSeq           : {clientSeq:30}
topicHash           : {topicHash:30}
SOW expiration      : {sowExpiration:>30}
iso8601 timestamp   : {isoTimestamp:>30}
timestamp           : {timestamp:30}
previous size       : {previousSize:30}
topic len           : {topicLen:30}
topic               : [{topic}]
data                : [{data}]"""
      elif self['version'] > 4:
         formatstr = """Entry               : {entryCount:30}
CRC                 : {crc:30}
type                : {typeStr:>30}
entry size          : {size:30}
msg len             : {messageLen:30}
msg type            : {messageTypeName:>30}
localTxId           : {localTxId:30}
previousLocalTxId   : {previousLocalTxId:30}
sourceTxId          : {sourceTxId:30}
source              : {sourceNameHash:30}
client              : {clientNameHash:30}
clientSeq           : {clientSeq:30}
topicHash           : {topicHash:30}
SOW expiration      : {sowExpiration:>30}
iso8601 timestamp   : {isoTimestamp:>30}
timestamp           : {timestamp:30}
previous size       : {previousSize:30}
topic len           : {topicLen:30}
topic               : [{topic}]
data                : [{data}]"""
      else:
         formatstr = """Entry               : {entryCount:30}
CRC                 : {crc:30}
type                : {typeStr:>30}
entry size          : {size:30}
msg len             : {messageLen:30}
msg type            : {messageTypeName:>30}
localTxId           : {localTxId:30}
sourceTxId          : {sourceTxId:30}
source              : {sourceNameHash:30}
client              : {clientNameHash:30}
clientSeq           : {clientSeq:30}
topicHash           : {topicHash:30}
SOW Key             : {sowKey:30}
iso8601 timestamp   : {isoTimestamp:>30}
timestamp           : {timestamp:30}
flags               : {flags:30}
topic len           : {topicLen:30}
topic               : [{topic}]
data                : [{data}]"""

      if self['keyLen'] > 0:
         formatstr = formatstr + """
key len             : {keyLen:>30}
key                 : [{key}]"""
      if self['version'] >= 6:
         formatstr = formatstr + """
correlation id len  : {correlationIdLen:>30}
correlation id      : [{correlationId}]"""
      if self['version'] > 1:
         formatstr = formatstr + """
auth ID len         : {authIdLen:>30}
auth ID             : [{authId}]
rep path len        : {replicationPathLen:>30}
rep path            : [{replicationPath}]"""
      formatstr = formatstr + "\n_____________________________________________________"
      return formatstr.format(**self)


class File:
   """A journal file reading object."""
   def __init__(self, filename):
      """Initializes self with a journal file path name. Opens and begins reading the journal file.

      :param filename: Path to the journal file.
      """
      self.filename = filename
      self.crc_generator = amps_common.Crc32()
      self.totalTxnBytes = 0
      self.totalTxnBytes = 0
      self.totalRemainingSize = 0
      self.entryCount = 0
      self._previousLocalTxId = 0
      self._padding = 0
      self.source_extents = {}
      self.is_compressed = False

      if self.filename.endswith("." + COMPRESSION_TYPE):
         self.in_file = gzip.open(self.filename,'rb')
         self.is_compressed = True
      else:
         self.in_file = os.fdopen(os.open(self.filename,os.O_RDONLY))

      # First AMPS_METADATA_SIZE bytes contains the AMPS journal metadata
      self.journal_metadata = amps_common.read_exact(self.in_file,AMPS_METADATA_SIZE)

      self.metadata_struct = struct.Struct('4sII32sI')
      self.magic,self.version,self.instanceId,self.versionString,self.crc = self.metadata_struct.unpack_from(self.journal_metadata)
      self.compressionType = ''
      self.compressionOptions = 0

      if(self.version >= 7):
         self.metadata_struct = struct.Struct('4sII32s8sQQI')
         self.magic,self.version,self.instanceId,self.versionString,self.compressionType,self.compressionOptions,self.flags,self.crc = self.metadata_struct.unpack_from(self.journal_metadata)
         self.compressionType = str(self.compressionType).strip(chr(0)).strip()

      if(not self.magic == b"AMPS"):
         # Not a valid journal file
         self.in_file.close()
         raise RuntimeError("Invalid journal file: %s" % self.filename)

      # Second AMPS_METADATA_SIZE bytes contains the AMPS journal extents
      self.in_file.seek(AMPS_METADATA_SIZE)
      self.journal_extents = amps_common.read_exact(self.in_file, AMPS_METADATA_SIZE)

      if(self.version < 7):
         self.extents_struct = struct.Struct('QQI')
         self.first,self.last,self.crc = self.extents_struct.unpack_from(self.journal_extents)
         self.first_timestamp = 0
         self.last_timestamp = 0
      else:
         self.extents_struct = struct.Struct('QqQqI')
         self.first,self.first_timestamp,self.last,self.last_timestamp,self.crc = self.extents_struct.unpack_from(self.journal_extents)

      self.stat = os.fstat(self.in_file.fileno())
      if self.filename.endswith("." + COMPRESSION_TYPE):
          self.fileSize = self.getFileSize()
      else:
          self.fileSize = self.stat.st_size
      self.versionString = self.versionString.decode().strip(chr(0)).strip()
      if(self.version == 1):
         self.record_struct = struct.Struct('IIIIQQQQQQQQQII')
         self._authId = ""
      elif self.version < 5:
         self.record_struct = struct.Struct('IIIIQQQQQQQQQIIII')
      elif self.version < 6:
         self.record_struct = struct.Struct('IIIIQQQQQQQQQQIIII')
      elif self.version < 7:
         self.record_struct = struct.Struct('IIIIQQQQQQQQQQIIIIII')
      else:
         self.record_struct = struct.Struct('IIHHIQQQQQQQQQQIIIIII')
      if(self.version >= 4):
         self.in_file.seek(AMPS_TX_OFFSET)

   def getSourceExtents(self):
       return self.source_extents

   def getExtents(self):
      """Returns a (first,last) tuple of extents, as declared in the journal file header."""
      return (self.first, self.first_timestamp, self.last, self.last_timestamp)
   def getInstanceId(self):
      """
      Returns the instance id field from the header of this journal file.
      """
      return self.instanceId
   def getVersionString(self):
      """
      Returns the version string from the header of this journal file.
      """
      return self.versionString
   def close(self):
      """
      Closes the file object underlying this journal file.
      """
      self.in_file.close()
   def getFileSize(self):
      """
      Returns the size of the journal file, as reported by the OS.
      """
      # if compressed file, then get uncompressed size
      if self.filename.endswith("." + COMPRESSION_TYPE):
          with open(self.filename, 'rb') as f:
              f.seek(-4,2)
              return struct.unpack('I',f.read(4))[0]
      else:
          return self.fileSize


   # NOTE: this function is bogus but retained because it was exposed
   # as a library function, it should be adding a 'Z' to UTC
   @staticmethod
   def iso8601_time(amps_time):
      global IS_LOCALTIME
      if (amps_time == 0):
          return 'unknown'
      """
      Converts amps journal time into an ISO8601 datetime.
      """
      it = amps_time/1000000 - 210866803200  # subtract the unix epoch
      ft = amps_time%1000000
      if not IS_LOCALTIME:
         return time.strftime("%Y%m%dT%H%M%S",time.gmtime(it)) + (".%.6d" % ft)
      else:
         return time.strftime("%Y%m%dT%H%M%S",time.localtime(it)) + (".%.6d" % ft)
     
   @staticmethod
   def _serializeISOTimestamp(it, ft):
      global IS_LOCALTIME
      if not IS_LOCALTIME:
         return time.strftime("%Y%m%dT%H%M%S",time.gmtime(it)) + (".%.6dZ" % ft)
      else:
         return time.strftime("%Y%m%dT%H%M%S",time.localtime(it)) + (".%.6d" % ft)

   @staticmethod
   def iso_timestamp(amps_time):
      if (amps_time == 0):
          return 'unknown'
      """
      Converts amps journal time into an ISO8601 datetime.
      """
      it = amps_time/1000000 - 210866803200  # subtract the unix epoch
      ft = amps_time%1000000
      return File._serializeISOTimestamp(it, ft)

   @staticmethod
   def iso_time_t(expiration_time):
      if (expiration_time == 0):
          return 'unknown'
      """
      Converts sow expiration time into an ISO8601 datetime.
      """
      return File._serializeISOTimestamp(expiration_time, 0)

   def records(self):
      global AMPS_TX_HEADER_SIZE
      global AMPS_MIN_TX_SIZE
      global IS_SOW_EXPIRATION_ISO
      global OMIT_DATA
      global DUMMY_DATA
      global IS_LOCALTIME
      """Returns an iterable object over the records in this journal file."""
      self.min_tx_size = AMPS_MIN_TX_SIZE
      self.offset = self.in_file.tell()
      self.record = amps_common.read_exact(self.in_file, self.min_tx_size)
      self.txnBytes = 0
      while(len(self.record) == self.min_tx_size):
         unpacked_record = self.record_struct.unpack_from(self.record)
         internal_debug("unpacked version %s record with %s entries" % (self.version, len(unpacked_record)))
         if(self.version == 1):
            expected_field_count = 15
            if len(unpacked_record) != expected_field_count:
                raise Exception("version %s record, expected %s fields, found %s" % (self.version, expected_field_count, len(unpacked_record)))
            self._crc,self._size,self._type,self._messageLen,self._messageTypeNameHash,self._localTxId,self._sourceTxId,self._sourceNameHash,self._clientNameHash,self._clientSeq,self._topicHash,self._sowKey,self._timestamp,self._flags,self._topicLen = unpacked_record
            self._authIdLen = 0
            self._keyLen = 0
            self._correlationIdLen = 0
            self._replicationPathLen = 0
            self._replicationPath = ""
            self._previousSize = 0
            self._sowExpiration = 0
         elif(self.version < 5):
            self._sowExpiration = 0
            self._previousSize = 0
            self._keyLen = 0
            self._correlationIdLen = 0
            expected_field_count = 17
            if len(unpacked_record) != expected_field_count:
                raise Exception("version %s record, expected %s fields, found %s" % (self.version, expected_field_count, len(unpacked_record)))
            self._crc,self._size,self._type,self._messageLen,self._messageTypeNameHash,self._localTxId,self._sourceTxId,self._sourceNameHash,self._clientNameHash,self._clientSeq,self._topicHash,self._sowKey,self._timestamp,self._flags,self._topicLen,self._authIdLen,self._replicationPathLen = unpacked_record
         elif(self.version < 6):
            self._sowKey = 0
            self._flags = 0
            self._keyLen = 0
            self._correlationIdLen = 0
            expected_field_count = 18
            if len(unpacked_record) != expected_field_count:
                raise Exception("version %s record, expected %s fields, found %s" % (self.version, expected_field_count, len(unpacked_record)))
            self._crc,self._size,self._type,self._messageLen,self._messageTypeNameHash,self._localTxId,self._previousLocalTxId,self._sourceTxId,self._sourceNameHash,self._clientNameHash,self._clientSeq,self._topicHash,self._sowExpiration,self._timestamp,self._previousSize,self._topicLen,self._authIdLen,self._replicationPathLen = unpacked_record
         elif(self.version < 7):
            self._sowKey = 0
            self._flags = 0
            expected_field_count = 20
            if len(unpacked_record) != expected_field_count:
                raise Exception("version %s record, expected %s fields, found %s" % (self.version, expected_field_count, len(unpacked_record)))
            self._crc,self._size,self._type,self._messageLen,self._messageTypeNameHash,self._localTxId,self._previousLocalTxId,self._sourceTxId,self._sourceNameHash,self._clientNameHash,self._clientSeq,self._topicHash,self._sowExpiration,self._timestamp,self._previousSize,self._topicLen,self._authIdLen,self._correlationIdLen,self._replicationPathLen,self._padding = unpacked_record
         else:
            self._sowKey = 0
            expected_field_count = 21
            if len(unpacked_record) != expected_field_count:
                raise Exception("version %s record, expected %s fields, found %s" % (self.version, expected_field_count, len(unpacked_record)))
            self._crc,self._size,self._type,self._flags,self._messageLen,self._messageTypeNameHash,self._localTxId,self._previousLocalTxId,self._sourceTxId,self._sourceNameHash,self._clientNameHash,self._clientSeq,self._topicHash,self._sowExpiration,self._timestamp,self._previousSize,self._topicLen,self._authIdLen,self._correlationIdLen,self._replicationPathLen,self._keyLen = unpacked_record

         if(self._crc == 0 and self._size == 0):
            break
         # Read remaining
         self.remainingBlocks = int((self._size/self.min_tx_size) - 1);
         if(self.remainingBlocks > 0):
            self.record = self.record + amps_common.read_exact(self.in_file, self.remainingBlocks * self.min_tx_size)

         # allow data only for sow_delete_by_bookmark and transfer messages
         is_omit_data_override = (self._type == 7 or self._type == 8)
         # Normalization of output (when possible)
         self.type = {0: 'publish',
                  1: 'delta-publish',
                  2: 'sow_delete_by_key',
                  3: 'sow_delete_by_query',
                  4: 'duplicate',
                  5: 'ack',
                  6: 'sow_delete_by_data',
                  7: 'sow_delete_by_bookmark',
                  8: 'transfer',
                  9: 'noop'}.get(self._type, 'unknown')

         self.flagsStr = {0: 'none',
                          1: 'compressed',
                          2: 'string key',
                          3: 'compressed, string key',
                          4: 'cancel'}.get(self._flags, 'none')

         self.messageTypeName = {11366176381677217403: 'fix',
                                 2827704697691937455:  'nvfix',
                                 10107872178429970057: 'xml',
                                 9900685383425431138:  'json',
                                 8442027542746405716:  'bson',
                                 10020990295791775699: 'binary',
                                 5817622476697324896:  'bflat',
                                 698723037243269950:   'protobuf'}.get(self._messageTypeNameHash,"%d (unknown)" % self._messageTypeNameHash)

         if(self.version == 1):
            self.topic = self.record[96:96+self._topicLen]
            self.data = DUMMY_DATA if OMIT_DATA else self.record[96+self._topicLen:96+self._messageLen+self._topicLen]
            self._authId = ""
         else:
            if (self.version < 5):
               header_size = 104
            elif (self.version < 6):
               header_size = 112
            else:
               header_size = AMPS_TX_HEADER_SIZE

            off = header_size
            length = header_size + self._topicLen
            self.topic = self.record[off:length]
            off = off + self._topicLen
            length = length + self._authIdLen
            self._authId = self.record[off:length]
            off = off + self._authIdLen
            length = length + self._keyLen
            self._key = self.record[off:length]
            off = off + self._keyLen
            length = length + self._correlationIdLen
            self._correlationId = self.record[off:length]
            off = off + self._correlationIdLen
            length = length + self._replicationPathLen
            self._replicationPath = self.record[off:length]
            off = off + self._replicationPathLen
            length = length + self._messageLen
            if not is_omit_data_override:
                self.data = DUMMY_DATA if OMIT_DATA else self.record[off:length]
            else:
                self.data = self.record[off:length]
                
         if 'compressed' in self.flagsStr:
            self.data = "compressed data"
         # if this is replicated then add to source extents
         if self._sourceNameHash:
            if self._sourceNameHash in self.source_extents:
               extents = self.source_extents[self._sourceNameHash]
               extents[2] = self._sourceTxId
               self.source_extents[self._sourceNameHash] = extents
            else:
               extents = [self._replicationPath,self._sourceTxId,self._sourceTxId]
               self.source_extents[self._sourceNameHash] = extents

         self._owner = 0
         self._requestPath = ""
         if self.type == "transfer" and len(self.data):
             self._owner = struct.unpack('Q', self.data[0:8])[0]
             self._requestPath = self.data[8:]

         try:
             data = self.data.decode()
         except UnicodeDecodeError as e:
             data = self.data

         if self._sowExpiration and IS_SOW_EXPIRATION_ISO:
             self._sowExpiration = File.iso_time_t(self._sowExpiration)

         # iso8601Timestamp is retained for backward compat where
         # timestamp did not include 'Z' suffix for utc timestamps and
         # required weird fixup of the formatted output.
         isoTimestamp = File.iso_timestamp(self._timestamp)
         iso8601Timestamp = isoTimestamp
         
         if not IS_LOCALTIME:
             iso8601Timestamp = iso8601Timestamp.strip('Z')
         
         yield Record({ 'crc': self._crc, 'size': self._size, 'type': self._type, 'messageLen': self._messageLen,
               'messageTypeNameHash': self._messageTypeNameHash, 'localTxId': self._localTxId, 'previousLocalTxId':self._previousLocalTxId,
               'sourceTxId': self._sourceTxId, 'sourceNameHash': self._sourceNameHash, 'clientNameHash': self._clientNameHash, 'clientSeq': self._clientSeq,
               'topicHash': self._topicHash, 'sowKey': self._sowKey, 'timestamp': self._timestamp, 'flags': self._flags,'flagsStr': self.flagsStr,
               'topicLen': self._topicLen, 'authIdLen': self._authIdLen, 'replicationPathLen': self._replicationPathLen, 'messageTypeName': self.messageTypeName,
               'topic': self.topic.decode(), 'data': data, 'authId': self._authId.decode(), 'replicationPath': self._replicationPath.decode(),
               'typeStr':self.type, 'version':self.version, 'entryCount': self.entryCount, 'iso8601Timestamp': iso8601Timestamp, 'isoTimestamp': isoTimestamp,
               'sowExpiration':self._sowExpiration, 'previousSize':self._previousSize, 'correlationId': self._correlationId.decode(),
               'correlationIdLen':self._correlationIdLen, 'key': self._key.decode(), 'keyLen':self._keyLen, 'offset':self.offset, 'owner':self._owner,
               'requestPath':self._requestPath})

         self.txnBytes = self.txnBytes + self._size
         self.offset = self.offset + self._size
         self.entryCount = self.entryCount + 1
         # if compressed then extents must be set correctly
         #if (self.is_compressed and (self.last == self._localTxId)):
         #    break
         # if not compressed then extents might not be set correctly
         if (not self.is_compressed and (self.offset + AMPS_MIN_TX_SIZE > self.fileSize)):
             break
         self.record = amps_common.read_exact(self.in_file, self.min_tx_size)

   def format_extents(self,is_journal_extents=False):
      if (self.version < 7):
         formatstr = """
File Name   : {0}
File Size   : {1}
Version     : {2}
Extents     : {3}\n_____________________________________________________"""
      else:
         formatstr = """
File Name       : {0}
File Size       : {1}
Version         : {2}
Extents         : {4}
First Timestamp : {5}
Last Timestamp  : {6}\n_____________________________________________________"""

      extents = "[{0}:{1}]".format(self.first, self.last)
      if self.first > 0 and self.last == 0:
         if not is_journal_extents:
            extents = "unwritten"

      if (self.version < 7):
         return formatstr.format(self.filename, self.fileSize, self.versionString, extents)
      else:
         first =  File.iso_timestamp(self.first_timestamp)
         last = File.iso_timestamp(self.last_timestamp)
         return formatstr.format(self.filename, self.fileSize, self.versionString, self.compressionType, extents, first, last)

   def __str__(self):
       return self.format_extents()
   
class Writer:
   """Used for writing to a new journal file."""
   def fill_gap(self, bytes_to_write):
      self.write_file.write('\0'.ljust(bytes_to_write,'\0'))
      
   # filename -- the name of the file to write
   # instanceId -- the name of the AMPS instance this journal corresponds to
   # extents -- (first txid, last txid)
   def __init__(self, filename, instanceId, extents):
      """Initializes self with the given filename, instanceID and declared extents.

      :param filename: the full path to the journal file to write.
      :type filename: str
      :param instanceId: the instance name to write into the journal header
      :type instanceId: str
      :param extents: a 2-entry tuple representing the first and last txid you plan to write.
      :type extents: tuple
      """
      self.crc_generator = amps_common.Crc32()
      self.instanceId = instanceId
      self.metadata_struct = struct.Struct('4sII32s8sQQI')
      self.extents_struct = struct.Struct('QqQqI')
      # let exceptions percolate up
      self.write_file = open(filename, 'wb')
      # These two member variables used for optional final noop entry
      self.last_txid = 0
      self.last_timestamp = 0

      # First AMPS_METADATA_SIZE bytes contains the AMPS journal metadata
      write_crc = 0xffffffff
      write_version = WRITER_VERSION
      write_version_string = WRITER_VERSION_STRING
      write_magic = 'AMPS'
      write_compression_type = WRITER_COMPRESSION_TYPE
      write_compression_options = WRITER_COMPRESSION_OPTIONS
      write_flags = 0
      # get the bytes of a first packed record
      record = self.metadata_struct.pack(write_magic,
                                         write_version,
                                         self.instanceId,
                                         write_version_string,
                                         write_compression_type,
                                         write_compression_options,
                                         write_flags,
                                         write_crc)
      # calculat a crc of everything in the record except its crc field
      write_crc = self.crc_generator.crc32(record[:-4], write_crc) & 0xffffffff
      # pack the bytes again, but this time including the calculated crc for the first four fields
      record = self.metadata_struct.pack(write_magic,
                                         write_version,
                                         self.instanceId,
                                         write_version_string,
                                         write_compression_type,
                                         write_compression_options,
                                         write_flags,
                                         write_crc)
      # write the first self.metadata_struct.size bytes
      self.write_file.write(record)
      # pad nulls all the way up to AMPS_TX_OFFSET bytes
      self.fill_gap(AMPS_TX_OFFSET - self.metadata_struct.size)

      (self.write_start_extent, self.write_start_timestamp, self.write_end_extent, self.write_end_timestamp) = extents
      self.write_extents()

      # Need some variables initialized for writing
      self.write_count = 0
      self._authId = ''
      self._authIdLen = 0

      self.write_record_format  = 'IIHHI'                 # 00-04
      self.write_record_format += 'QQQQQQQQQQ'            # 05-14
      self.write_record_format += 'IIIIII'                # 15-20
      self.write_record_format += '{topicLen}s'           #    21
      self.write_record_format += '{authIdLen}s'          #    22
      self.write_record_format += '{keyLen}s'             #    23
      self.write_record_format += '{correlationIdLen}s'   #    24
      self.write_record_format += '{replicationPathLen}s' #    25
      self.write_record_format += '{messageLen}s'         #    26

      self.write_file_offset = AMPS_TX_OFFSET
      self.last_write_size = 0

   def write_extents(self):
      # Second AMPS_METADATA_SIZE bytes contains the AMPS journal extents
      self.write_file.seek(AMPS_METADATA_SIZE)
      write_crc = 0xffffffff
      record = self.extents_struct.pack(self.write_start_extent,
                                        self.write_start_timestamp,
                                        self.write_end_extent,
                                        self.write_end_timestamp,
                                        write_crc)
      write_crc = self.crc_generator.crc32(record[:-4], write_crc) & 0xffffffff
      record = self.extents_struct.pack(self.write_start_extent,
                                        self.write_start_timestamp,
                                        self.write_end_extent,
                                        self.write_end_timestamp,
                                        write_crc)
      self.write_file.write(record)
      self.fill_gap(AMPS_METADATA_SIZE - self.extents_struct.size)

   def create_noop(self, byteCount):
      global AMPS_TX_HEADER_SIZE
      # Noop records must set key fields, and remaining ones as null
      noop_map = {
           'size': byteCount,
           'type': 9, # Noop
           'localTxId': self.last_txid,
           'timestamp': self.last_timestamp,
           'offset': self.write_file_offset # + byteCount
      }
      for key in ['topic', 'authId', 'key',
                  'correlationId', 'replicationPath', 'data']:
          noop_map[key] = ''
      for key in ['flags', 'offset',
                  'messageTypeNameHash', 'sourceNameHash',
                  'previousLocalTxId', 'sourceTxId',
                  'clientNameHash', 'clientSeq', 'topicHash',
                  'sowExpiration', 'previousSize',
                  'topicLen', 'authIdLen', 'keyLen',
                  'correlationIdLen', 'replicationPathLen',
                  'messageLen']:
          noop_map[key] = 0
      messageLen = byteCount - AMPS_TX_HEADER_SIZE

      data = '\0'.ljust(messageLen,'\0')
      noop_map['messageLen'] = messageLen
      noop_map['data'] = data
      return Record(noop_map)
   
   def write_noop(self, byteCount):
      self.write_file.seek(self.write_file_offset)
      record = self.create_noop(byteCount)
      write_crc = 0xffffffff
      format_str = self.write_record_format.format(**record)
      write_record_struct = struct.Struct(format_str)
      recordBytes = self.pack(write_record_struct, write_crc, record)

      write_crc = self.crc_generator.crc32(recordBytes[4:], write_crc) & 0xffffffff
      recordBytes = self.pack(write_record_struct, write_crc, record)

      self.write_file.write(recordBytes)

      self.last_write_size = byteCount
      self.write_file_offset += byteCount
      
   def close(self):
      """Finalizes writes to self and closes the file. Must be called for the written journal file
      to be usable with AMPS."""
      self.write_file.seek(self.write_file_offset)

      # Write a noop entry if the last journal entry isn't already aligned
      bytesToWrite = AMPS_TX_OFFSET - (self.write_file_offset % AMPS_TX_OFFSET)
      if bytesToWrite and bytesToWrite != AMPS_TX_OFFSET:
          self.write_noop(bytesToWrite)

      self.write_extents()
      self.write_file.close()

   def pack(self, struct, crc, record):
       return struct.pack(crc,                          # 00
                         record['size'],                # 01
                         record['type'],                # 02
                         record['flags'],               # 03
                         record['messageLen'],          # 04
                         record['messageTypeNameHash'], # 05
                         record['localTxId'],           # 06
                         record['previousLocalTxId'],   # 07
                         record['sourceTxId'],          # 08
                         record['sourceNameHash'],      # 09
                         record['clientNameHash'],      # 10
                         record['clientSeq'],           # 11
                         record['topicHash'],           # 12
                         record['sowExpiration'],       # 13
                         record['timestamp'],           # 14
                         self.last_write_size,          # 15
                         record['topicLen'],            # 16
                         record['authIdLen'],           # 17
                         record['correlationIdLen'],    # 18
                         record['replicationPathLen'],  # 19
                         record['keyLen'],              # 20
                         str(record['topic']),          # 21
                         str(record['authId']),         # 22
                         str(record['key']),            # 23
                         str(record['correlationId']),  # 24
                         str(record['replicationPath']),# 25
                         str(record['data']))           # 26

   def write(self, record):
      global AMPS_MIN_TX_SIZE
      global AMPS_MIN_TX_SIZE_MASK
      """Writes a record to the journal file.

      :param record: a dictionary containing the required keys for an AMPS journal file.
      :type record: dict
      """
      self.write_file.seek(self.write_file_offset)
      write_crc = 0xffffffff
      padding = 0
      format_str = self.write_record_format.format(**record)
      write_record_struct = struct.Struct(format_str)
      recordBytes = self.pack(write_record_struct, write_crc, record)
      alignedByteCount = (len(recordBytes) + AMPS_MIN_TX_SIZE_MASK) & ~AMPS_MIN_TX_SIZE_MASK
      
      #we may have added metadata fields that generate an upgrade entry larger or smaller than the original
      if alignedByteCount != record['size']:
          record['size'] = alignedByteCount
          write_record_struct = struct.Struct(format_str)
          recordBytes = self.pack(write_record_struct, write_crc, record)

      write_crc = self.crc_generator.crc32(recordBytes[4:], write_crc) & 0xffffffff
      recordBytes = self.pack(write_record_struct, write_crc, record)

      self.write_file.write(recordBytes)
      if (alignedByteCount > len(recordBytes)):
          bytesToWrite = alignedByteCount - len(recordBytes);
          self.fill_gap(bytesToWrite)
      self.last_write_size = record['size']
      self.write_file_offset += record['size']

      # These two member variables used for optional final noop entry
      self.last_txid = record['localTxId']
      self.last_timestamp = record['timestamp']
      
      self.write_count += 1
      if(self.write_start_extent == 0 or self.write_start_extent > record['localTxId']):
         self.write_start_extent = record['localTxId']
      if(self.write_end_extent == 0 or self.write_end_extent < record['localTxId']):
         self.write_end_extent = record['localTxId']
