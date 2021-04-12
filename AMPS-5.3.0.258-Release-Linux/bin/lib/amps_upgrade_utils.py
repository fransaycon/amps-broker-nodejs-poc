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
from __future__ import absolute_import
from optparse import OptionParser, OptionGroup
import sys

from amps_server import COMPONENTS

import os
from os.path import join, dirname, exists, isdir, isabs, basename
from os import makedirs, listdir
from shutil import copy2, copytree, rmtree, move
import glob
import logging


def remove(file):
    logging.getLogger("amps_upgrade").debug("remove(%s)" % file)
    if not exists(file):
        return
    if isdir(file):
        rmtree(file)
    else:
        os.remove(file)


def copy(src, dest, msg=""):
    logging.getLogger("amps_upgrade").debug("copy(%s, %s)" % (src, dest))
    if isdir(src):
        copytree(src, dest)
    else:
        parent = dirname(dest)
        if not exists(parent):
            makedirs(parent)
        copy2(src, dest)


def list_journal_files(dir):
    files = []
    for ext in [ "journal.gz", "journal" ]:
        for f in glob.glob("%s/*.%s" % (dir, ext)):
            files.append(f)
    return files


class FileStage:

    file_types = COMPONENTS

    def __init__(self, config, tmpdir, logger=None):
        self.config = config
        self.root = join(tmpdir, "amps_upgrade")
        self.logger = logger

        self.orig = join(self.root, "orig")
        self.orig_abs = join(self.orig, "abs")
        self.orig_rel = join(self.orig, "rel")

        self.next = join(self.root, "next")
        self.next_abs = join(self.next, "abs")
        self.next_rel = join(self.next, "rel")

        self.temp = join(self.root, "temp")
        self.temp_abs = join(self.temp, "abs")
        self.temp_rel = join(self.temp, "rel")

        self.logger.debug("filestage inialized under %s" % self.root)
        self.entries = {}


    def purge(self):
        self.logger.debug("filestage purging ...")
        if exists(self.root):
            self.logger.debug("rmtree(%s)" % self.root)
            rmtree(self.root)
        for d in [self.orig_abs, self.orig_rel,
                  self.next_abs, self.next_rel,
                  self.temp_abs, self.temp_rel]:
            self.logger.debug("makedirs(%s)" % d)
            makedirs(d)
        self.entries = {}
        self.logger.debug("filestore purged.")

    #
    # Provides an instance of the Entry class (see its comments/documentation).
    #
    # assumes we're engaged in the work of upgrading files from an older AMPS server (henceforth v1)
    # to the current AMPS server (henceforth v2), meaning the version of AMPS that this file was distributed with.
    #
    # So, note: v1 and v2 do not refer to actual versions but, rather, indicate the
    # older vs the newer AMPS version involved in this upgrade process.
    #
    # v1_live_path: path to a file created/used by a v1 AMPS instance,
    #               will be used to constructe the returned Entry's 'live' field, amongst other things
    # v2_live_path: this will be used as a basis for the returned Entry's 'live_upgraded' field,
    #               provides a way to inform the Entry class of any changes in file naming convention (see example in Entry comments)
    #
    # both arguments, if not absolute, will be interpreted relative to this FileStage
    #

    def get_entry(self, v1_live_path, v2_live_path=None):
        # if only one path version is provided we can assume there's no difference in path construction between the two AMPS versions
        if v2_live_path is None:
            v2_live_path = v1_live_path
        if v1_live_path not in self.entries:
            self.entries[v1_live_path] = FileStage.Entry(self,
                                                         v1_live_path,
                                                         v2_path=v2_live_path,
                                                         logger=self.logger)
        return self.entries[v1_live_path]


    #
    # Entry instances should be obtained from Stage.get_entry(), see also: its docs/comments
    # This Enty class builds the paths used in upgrading a single older version (henceforth 'v1')
    # AMPS server file to the current version of the AMPS distribution this file is included in (henceforth 'v2')
    #
    # A few different paths are used in the process of reading a production v1 file and producing a production v2 file:
    #
    # live: the path of a v1 file previously created and used by an AMPS v1 server,
    #       the name and relativeness of this path are used in constructing the other paths used by the Entry
    # orig: the path of a backup copy of the live file
    # next: the path of a v2 version of live  intended for use by the  v2 AMPS server
    # temp: the path used if some  temporary file space is needed by the v1 -> v2 upgrade process
    # live_upgraded: the path of the upgraded and published v2 file,
    #                 located in the production directory structure and ready for use by the v2 AMPS server
    # live vs live_upgraded: AMPS v2 may have evolved its naming convention for live since AMPS v1,
    #                        live_upgraded adheres to the v2 naming convention
    #                        e.g.: in 4.0.0 mytopic.sow may have become fix.mytopic.sow
    #
    # most of these paths are constructed relative to a FileStage, provided to the constructor
    #
    # aside from building and providing these named paths,
    # this Entry class doesn't provide any file manipulation operations
    #
    # actual File copy/move/delete operations are provided by the FileStage class
    #
    # upgrade operations are provided by the amps_<filetype>.py lib files and invoked by the amps_upgrade script
    #
    # The rough lifecycle for an Entry is:
    # 1. make a backup copy of live to orig
    # 2. upgrade create a v2 version of orig at next, using temp for temporary space if needed
    # 3. publish next to live_upgraded via a copy/move operation
    #
    # the differentiation between (2) and (3) allows us to complete all upgrade transcoding
    # prior to moving anything into v2 production because of this, the execution of (3) only
    # involves simple operations that should be faster, simpler and less exception-prone than
    # (2), hopefully providing a cleaner transition from
    # the "upgraded" to "deployed to v2 production" states
    #
    class Entry:

        def __init__(self, stage, v1_path, v2_path=None, logger=None):
            if v2_path is None:
                v2_path = v1_path
            self.logger = logger
            if isabs(v1_path):
                # v1_path is absolute, so the leading slash must be trimmed from it when it is
                # joined with prefixes obtained from stage
                # since v1_path is absolute, it can just be assigned to live
                self.live = v1_path
                self.orig = join(stage.orig_abs, v1_path[1:])
                self.temp = join(stage.temp_abs, v1_path[1:])
            else:
                # v1_path is relative, it can simply be joined with prefixes defined in stage
                # since v1_path is relative, it must be joined to the stage's working directory
                self.live = join(stage.config.working_directory, v1_path)
                self.orig = join(stage.orig_rel, v1_path)
                self.temp = join(stage.temp_rel, v1_path)

            if (isabs(v2_path)):
                self.next = join(stage.next_abs, v2_path[1:])
            else:
                self.next = join(stage.next_rel, v2_path)

            # upgraded_live is where the upgraded version of live will wind up
            # if we changed naming convention they'll have a different basenme
            # (basename e.g.): live=topic.sow and upgraded_live=fix.topic.sow
            self.live_upgraded = join(dirname(self.live), basename(self.next))
            self.live_upgraded = self.live_upgraded.encode('ascii', 'ignore')
            self.live = self.live.encode('ascii', 'ignore')
            self.orig = self.orig.encode('ascii', 'ignore')
            self.next = self.next.encode('ascii', 'ignore')
            self.temp = self.temp.encode('ascii', 'ignore')

        def __str__(self):
            return "FileStage.Entry:\n ... live: %s\n ... live_upgraded: %s\n ... orig: %s\n ... next: %s\n ... temp: %s" % (self.live, self.live_upgraded, self.orig, self.next, self.temp)

        def __repr__(self):
            return self.__str__()


    #
    # returns a list of entries where:
    #
    #  - base directories exist
    #  - live is copied to orig
    #  - temp is deleted
    #
    def files(self, component):
        self.logger.debug("filestage fetching %s file entries" % component)
        results = []
        if component == "ack":
            for txn_log in self.config.data.txn_logs:
                # older versions of AMPS built ack file paths as ${JournalDirectory}/clients.ack
                #
                v1_live_path = join(txn_log["JournalDirectory"], "clients.ack")
                v2_live_path = join(txn_log["JournalDirectory"], "%s.clients.ack" % self.config.data.name)
                earlier_ack_entry = self.get_entry(v1_live_path, v2_live_path=v2_live_path)
                later_ack_entry = self.get_entry(v2_live_path)
                the_result = None
                if exists(earlier_ack_entry.live):
                    the_result = earlier_ack_entry
                elif exists(later_ack_entry.live):
                    the_result = later_ack_entry
                else:
                    raise Exception("failed to find ack file for journal_directory='%s' and name='%s'" % (txn_log["JournalDirectory"], self.config.data.name))
                results.append(the_result)
                #self.get_entry(join(txn_log["JournalDirectory"], "clients.ack")))
        elif component == "sow":
            for topic_def in self.config.data.topic_defs:
                #print "topic_def: %s" % topic_def
                topic_esc = topic_def["Topic"].lstrip("/").replace("/", ".")
                #print "topic_esc: %s" % topic_esc
                msgtype_esc = topic_def["MessageType"].lstrip("/").replace("/", ".")
                # versions of AMPS older than the current one built sow files using just the topic: ${topic}.sow
                # this assumes we're upgrading from one of these older AMPS versions
                # as upgrading from the AMPS version where the switch happened becomes a possibility, we'll need
                # to deal with the possibility that the v1_live_path could be constructed eaither way
                # dealing with this possibility will have to use the fact that the v1_live_path must exist in order to be upgraded
                # so rather than checking server version we'll just have to use file existance
                v1_live_path = topic_def["FileName"].replace("%n",topic_esc)
                # this was introduced in the AMPS version where we prepended the msgtype to sow files
                # this statement assumes that the current AMPS version has retained this msgtype.topic.sow filename
                v2_live_path = topic_def["FileName"].replace("%n","%s.%s" % (topic_esc, msgtype_esc))
                # entry for the case where we're upgrading from older-named sow file
                earlier_sow_entry = self.get_entry(v1_live_path, v2_live_path=v2_live_path)
                # entry for the case where we're upgrading from sow file with latest naming convention
                later_sow_entry = self.get_entry(v2_live_path)
                if   exists(earlier_sow_entry.live):
                    results.append(earlier_sow_entry)
                elif exists(later_sow_entry.live):
                    results.append(later_sow_entry)
                else:
                    # TODO: publish this as a warn() on a proper python logging.Logger
                    # this case is hit for sow configurations that produce no file on disk (like transient)
                    self.logger.warning("no sow file found for topic='%s' and msgtype='%s' ... assuming it is a transient or empty sow" % (topic_esc, msgtype_esc))
        elif component == "jnl":
            for tlog in self.config.data.txn_logs:
                dir_key = "JournalDirectory"
                if dir_key in tlog:
                    results.append(self.get_entry(tlog[dir_key]))
                else:
                    raise Exception("Missing required child element under transaction log element: '%s'" % dir_key)
                archive_key = "JournalArchiveDirectory"
                if archive_key in tlog:
                    results.append(self.get_entry(tlog[archive_key]))
        else:
            raise Exception("unrecognized component: '%s'" % component)
        if len(results) == 0:
            self.logger.debug("no %s files found" % component)
        for entry in results:
            # verify parent dirs exist
            for file in [ entry.orig, entry.next, entry.temp ]:
                if not exists(dirname(file)):
                    makedirs(dirname(file))
            if component == "jnl":
                # create orig if it doesn't already exist
                if not exists(entry.orig):
                    makedirs(entry.orig)
                # copy live journal files to orig
                for file in listdir(entry.live):
                    if (file.endswith(".journal") or file.endswith(".journal.gz")) and not exists(join(entry.orig, file)):
                        copy(join(entry.live, file), join(entry.orig, file), msg="creating backup file 'entry.orig'")
            else:
                # create orig if it's not there already
                if not exists(entry.orig):
                    copy(entry.live, entry.orig, msg="creating backup file 'entry.orig'")
                # purge the temp file if it exists
                if exists(entry.temp):
                    remove(entry.temp)
        self.logger.debug("returning %s %s file entries:" % (len(results), component))
        return results


    def publish(self):
        self.logger.debug(">>> exporting any upgraded files to live system")
        self.logger.debug(">>> exporting any upgraded files to live system")
        for type in FileStage.file_types:
            self.logger.debug("checking %s files ..." % type)
            self.logger.debug("checking %s files ..." % type)
            for entry in self.files(type):
                self.logger.debug("file entry: %s" % entry)
                self.logger.debug("file entry: %s" % entry)
                if type == "jnl":
                    files = list_journal_files(entry.next)
                    if len(files) == 0:
                        self.logger.debug("no %s files to export" % type)
                        self.logger.debug("no %s files to export" % type)
                        continue
                    for next_file in files:
                        live_file = join(entry.live, basename(next_file))
                        self.logger.debug("removing live file: %s" % live_file)
                        self.logger.debug("removing live file: %s" % live_file)
                        remove(live_file)
                        self.logger.debug("copying in upgraded file: %s -> %s" % (next_file, live_file))
                        self.logger.debug("copying in upgraded file: %s -> %s" % (next_file, live_file))
                        copy(next_file, live_file, msg="point3")
                else:
                    if not exists(entry.next):
                        self.logger.debug("no %s files to export" % type)
                        self.logger.debug("no %s files to export" % type)
                        continue
                    if exists(entry.live):
                        self.logger.debug("removing live file: %s" % entry.live)
                        self.logger.debug("removing live file: %s" % entry.live)
                        remove(entry.live)
                    if exists(entry.live_upgraded):
                        self.logger.debug("removing live file: %s" % entry.live_upgraded)
                        self.logger.debug("removing live file: %s" % entry.live_upgraded)
                        remove(entry.live_upgraded)
                    self.logger.debug("copying in upgraded file: %s -> %s" % (entry.next, entry.live_upgraded))
                    self.logger.debug("copying in upgraded file: %s -> %s" % (entry.next, entry.live_upgraded))
                    copy(entry.next, entry.live_upgraded, msg="point4")
        self.logger.debug("<<< all staged files exported to live directory")
        self.logger.debug("<<< all staged files exported to live directory")
