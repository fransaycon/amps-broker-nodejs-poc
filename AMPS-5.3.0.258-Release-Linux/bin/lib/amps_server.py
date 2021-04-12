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
from __future__ import print_function
from xml.sax.saxutils import escape
import os
import os.path
import re
import subprocess
import sys
import xml.sax

COMPONENTS = [ "sow", "jnl", "ack" ]


class Instance:

    def __init__(self, install_dir):
        self._install_dir = install_dir
        self._amp_server = os.path.join(self._install_dir, "bin", "ampServer")
        self._version = None

    def _raw_version(self):
        p = subprocess.Popen([self._amp_server, "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()[0:2]
        v = str(err.split()[1])
        if v.startswith("develop."):
            return "develop"
        else:
            return ".".join([ s for s in v.split(".") if len(s) == 1 ])

    def version(self):
        if self._version is None:
            self._version = self._raw_version()
        return self._version


class Config:

    def __init__(self, config_file, working_directory):
        self.config_file = config_file
        self.working_directory = working_directory
        self.data = Config.ConfigHandler()
        xml.sax.parse(open(config_file), self.data)

    def dump_to(self, out):
        out.write("\n>>>> config info dump\n")
        out.write("conig_file: %s\n" % self.config_file)
        self.data.dump_to(out)
        out.write("\n<<<< config info dump\n")
        out.flush()

    class ConfigHandler(xml.sax.ContentHandler):

        #
        # Not implemented: MessageTypes, Replication
        #
        def __init__(self):
            xml.sax.ContentHandler.__init__(self)
            self.ele_stack = []
            self.txt_stack = []

            self.name = None
            self.sow_stats_interval = None
            self.mini_dump_directory = None
            self.config_validation = None
            self.admin = {}
            self.topic_defs = []
            self.view_defs = []
            self.txn_logs = []
            self.logs = []
            self.transports = []
            self.modules = []
            self.authentications = []
            self.entitlements = []
            self.projections = []
            self.groupings = []


        def startElement(self, name, attrs):

            if len(self.ele_stack) > 0:
                path = "/".join(self.ele_stack[1:] + [name])
                map = {
                    "SOW/TopicDefinition": self.topic_defs,
                    "SOW/Topic": self.topic_defs,
                    "SOW/ViewDefinition": self.view_defs,
                    "SOW/View": self.view_defs,
                    "TopicMetaData/TopicDefinition": self.topic_defs,
                    "TopicMetaData/Topic": self.topic_defs,
                    "TopicMetaData/ViewDefinition": self.view_defs,
                    "TopicMetaData/View": self.view_defs,
                    "TransactionLog": self.txn_logs,
                    "Logging/Target": self.logs,
                    "Transports/Transport": self.transports,
                    "Authentication": self.authentications,
                    "Entitlement": self.entitlements,
                    "Modules/Module": self.modules,
                }
                if path in map:
                    map[path].append({})
                else:
                    map = {
                        "Modules/Module/Options": [ "options", self.modules ],
                        "Modules/Module/Authentication": [ "authentications", self.modules ],
                        "Modules/Module/Entitlement": [ "entitlements", self.modules ],
                        "SOW/ViewDefinition/Projection": [ "projections", self.view_defs ],
                        "SOW/ViewDefinition/Grouping": [ "groupings", self.view_defs ],
                        "SOW/View/Projection": [ "projections", self.view_defs ],
                        "SOW/View/Grouping": [ "groupings", self.view_defs ],
                        "TopicMetaData/ViewDefinition/Projection": [ "projections", self.view_defs ],
                        "TopicMetaData/ViewDefinition/Grouping": [ "groupings", self.view_defs ],
                        "TopicMetaData/View/Projection": [ "projections", self.view_defs ],
                        "TopicMetaData/View/Grouping": [ "groupings", self.view_defs ],
                        "TransactionLog/Topic": [ "topics", self.txn_logs ],
                    }
                    if path in map:
                        (key, list) = map[path]
                        if key not in list[-1]:
                            list[-1][key] = []
                        list[-1][key].append({})

            if name == "TopicDefinition":
                if False:
                    print(type(self.topic_defs))
                    print("topic_defs len: %s" %  len(self.topic_defs))
                    print("name: %s" % name)
                    print("path: %s" % path)
                    print("txt_stack: %s" % self.txt_stack)
                    print("ele_stack: %s" % self.ele_stack)
                    print("topic_defs: %s" % self.topic_defs)
                self.topic_defs[-1].update({
                        "RecordSize": 512,
                        "InitialSize": 10000,
                        "IncrementSize": 10000,
                        })
                #raise Exception("ZTOP")

            self.ele_stack.append(name)
            self.txt_stack.append("")

        def endElement(self, name):
            # Expand any env vars embedded in text values
            txt = os.path.expandvars(self.txt_stack[-1]).strip()
            if len(self.ele_stack) > 1:
                path = "/".join(self.ele_stack[1:])
                #
                # Transports
                #
                if path == "Name":
                    self.name = txt
                elif path == "SOWStatsInterval":
                    self.sow_stats_interval = txt
                elif path == "MiniDumpDirectory":
                    self.mini_dump_directory = txt
                elif path == "ConfigValidation":
                    self.config_validation = txt
                #
                # Admin
                #
                elif re.match("Admin/.*", path):
                    self.admin[name] = txt
                #
                # Authentication
                #
                elif re.match("Authentication/.*", path):
                    self.authentications[-1][name] = txt
                #
                # Entitlement
                #
                elif re.match("Entitlement/.*", path):
                    self.entitlements[-1][name] = txt
                #
                # Transports
                #
                elif re.match("Transports/Transport/.*", path):
                    self.transports[-1][name] = txt
                #
                # Logging
                #
                elif re.match("Logging/Target/.*", path):
                    self.logs[-1][name] = txt
                #
                # TransactionLog
                #
                elif re.match("TransactionLog/Topic/.*", path):
                    self.txn_logs[-1]["topics"][-1][name] = txt
                elif re.match("TransactionLog/.*", path) and name not in ["Topic"]:
                    self.txn_logs[-1][name] = txt
                #
                # Topic Defs
                #
                elif re.match("TopicMetaData/TopicDefinition/.*", path):
                    self.topic_defs[-1][name] = txt
                elif re.match("SOW/TopicDefinition/.*", path):
                    self.topic_defs[-1][name] = txt
                elif re.match("TopicMetaData/Topic/.*", path):
                    self.topic_defs[-1][name] = txt
                elif re.match("SOW/Topic/.*", path):
                    self.topic_defs[-1][name] = txt
                #
                # View Defs
                #
                elif re.match("TopicMetaData/ViewDefinition/Projection/.*", path):
                    self.view_defs[-1]["projections"][-1][name] = txt
                elif re.match("TopicMetaData/ViewDefinition/Grouping/.*", path):
                    self.view_defs[-1]["groupings"][-1][name] = txt
                elif re.match("TopicMetaData/ViewDefinition/.*", path) and name not in ["Projection", "Grouping"]:
                    self.view_defs[-1][name] = txt
                elif re.match("TopicMetaData/View/Projection/.*", path):
                    self.view_defs[-1]["projections"][-1][name] = txt
                elif re.match("TopicMetaData/View/Grouping/.*", path):
                    self.view_defs[-1]["groupings"][-1][name] = txt
                elif re.match("TopicMetaData/View/.*", path) and name not in ["Projection", "Grouping"]:
                    self.view_defs[-1][name] = txt
                #
                # Modules
                #
                elif re.match("Modules/Module/Authentication/.*", path):
                    self.modules[-1]["authentications"][-1][name] = txt
                elif re.match("Modules/Module/Entitlement/.*", path):
                    self.modules[-1]["entitlements"][-1][name] = txt
                elif re.match("Modules/Module/Options/.*", path):
                    self.modules[-1]["options"][-1][name] = txt
                elif re.match("Modules/Module/.*", path) and name not in ["Options", "Authentication", "Entitlement"]:
                    self.modules[-1][name] = txt
            self.txt_stack.pop()
            self.ele_stack.pop()

        def characters(self, content):
            self.txt_stack[-1] += content

        def dump_to(self, out):
            out.write("Name: %s\n" % self.name)
            out.write("SOW Stats Interval: %s\n" % self.sow_stats_interval)
            out.write("Mini Dump Directory: %s\n" % self.mini_dump_directory)
            out.write("Config Validation: %s\n\n" % self.config_validation)
            out.write("Admin:\n")
            out.write("%s\n" % self.admin)
            out.write("\n")
            map = {
                "Authentications": self.authentications,
                "Entitlements": self.entitlements,
                "Logs": self.logs,
                "Modules": self.modules,
                "SOW Topic Defs": self.topic_defs,
                "Transaction Logs": self.txn_logs,
                "Transports": self.transports,
                "View Defs": self.view_defs,
            }
            for key in map:
                if len(map[key]) > 0:
                    out.write("%s:\n" % key)
                    for item in map[key]:
                        out.write("%s\n\n" % map[key])
            out.flush()


from os.path import join, dirname, exists, isdir, isabs
from os import makedirs, listdir
from shutil import copy2, copytree, rmtree

def remove(file):
    printer.v("remove(%s)" % file)
    if not exists(file):
        return
    if isdir(file):
        rmtree(file)
    else:
        os.remove(file)

def copy(src, dest):
    printer.v("copy(%s, %s)" % (src, dest))
    if isdir(src):
        copytree(src, dest)
    else:
        parent = dirname(dest)
        if not exists(parent):
            makedirs(parent)
        copy2(src, dest)
