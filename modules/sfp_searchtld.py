#-------------------------------------------------------------------------------
# Name:         sfp_searchtld
# Purpose:      SpiderFoot plug-in for identifying the existence of this target
#               on other TLDs.
#
# Author:      Steve Micallef <steve@binarypool.com>
#
# Created:     31/08/2013
# Copyright:   (c) Steve Micallef 2013
# Licence:     GPL
#-------------------------------------------------------------------------------

import dns.resolver
import socket
import sys
import re
import time
import random
import threading
from sflib import SpiderFoot, SpiderFootPlugin, SpiderFootEvent

# SpiderFoot standard lib (must be initialized in setup)
sf = None

class sfp_searchtld(SpiderFootPlugin):
    """Search all Internet TLDs for domains with the same name as the target."""

    # Default options
    opts = {
        'activeonly':   True, # Only report domains that have content (try to fetch the page)
        'checkcommon':  True, # For every TLD, try the common sub-TLDs like com, net, etc. too
        'commontlds':   ['com', 'info', 'net', 'org', 'biz', 'co', 'edu', 'gov', 'mil' ],
        'tldlist':      "http://data.iana.org/TLD/tlds-alpha-by-domain.txt",
        'skipwildcards':    True,
        'maxthreads':   100
    }

    # Option descriptions
    optdescs = {
        'activeonly':   "Only report domains that have content (try to fetch the page)?",
        'checkcommon':  "For every TLD, also prepend each common sub-TLD (com, net, ...)",
        "commontlds":   "Common sub-TLDs to try when iterating through all Internet TLDs.",
        "tldlist":      "The list of all Internet TLDs.",
        "skipwildcards":    "Skip TLDs and sub-TLDs that have wildcard DNS.",
        "maxthreads":   "Number of simultaneous DNS resolutions to perform at once."
    }

    # Internal results tracking
    results = list()

    # Target
    baseDomain = None

    # Track TLD search results between threads
    tldResults = dict()

    def setup(self, sfc, target, userOpts=dict()):
        global sf

        sf = sfc
        self.baseDomain = target
        self.results = list()

        for opt in userOpts.keys():
            self.opts[opt] = userOpts[opt]

    # What events is this module interested in for input
    def watchedEvents(self):
        return None

    def tryTld(self, target):
        try:
            addrs = socket.gethostbyname_ex(target)
            self.tldResults[target] = True
        except BaseException as e:
            self.tldResults[target] = False

    def tryTldWrapper(self, tldList):
        self.tldResults = dict()
        running = True
        i = 0
        t = []

        # Spawn threads for scanning
        sf.info("Spawning threads to check TLDs: " + str(tldList))
        for tld in tldList:
            t.append(threading.Thread(name='sfp_searchtld_' + tld,
                target=self.tryTld, args=(tld,)))
            t[i].start()
            i += 1

        # Block until all threads are finished
        while running:
            found = False
            for rt in threading.enumerate():
                if rt.name.startswith("sfp_searchtld_"):
                    found = True

            if not found:
                running = False

        for res in self.tldResults.keys():
            if self.tldResults[res]:
                self.sendEvent(None, res)

    # Store the result internally and notify listening modules
    def sendEvent(self, source, result):
        if result == self.baseDomain:
            return

        sf.info("Found a TLD with the target's name: " + result)
        self.results.append(result)

        # Inform listening modules
        if self.opts['activeonly']:
            if self.checkForStop():
                return None

            pageContent = sf.fetchUrl('http://' + result)
            if pageContent['content'] != None:
                evt = SpiderFootEvent("SIMILARDOMAIN", result, self.__name__)
                self.notifyListeners(evt)
        else:
            evt = SpiderFootEvent("SIMILARDOMAIN", result, self.__name__)
            self.notifyListeners(evt)

    # Search for similar sounding domains
    def start(self):
        keyword = sf.domainKeyword(self.baseDomain)
        sf.debug("Keyword extracted from " + self.baseDomain + ": " + keyword)
        targetList = list()

        # No longer seems to work.
        #if "whois" in self.opts['source'] or "ALL" in self.opts['source']:
        #    self.scrapeWhois(keyword)

        # Look through all TLDs for the existence of this target keyword
        tldlistContent = sf.fetchUrl(self.opts['tldlist'])
        if tldlistContent['content'] == None:
            sf.error("Unable to obtain TLD list from " + self.opts['tldlist'], False)
        else:
            for tld in tldlistContent['content'].lower().splitlines():
                if tld.startswith("#"):
                    continue

                if self.opts['skipwildcards'] and sf.checkDnsWildcard(tld):
                    continue

                tryDomain = keyword + "." + tld

                if self.checkForStop():
                    return None

                if len(targetList) <= self.opts['maxthreads']:
                    targetList.append(tryDomain)
                else:
                    self.tryTldWrapper(targetList)
                    targetList = list()

                # Try to resolve <target>.<subTLD>.<TLD>
                if self.opts['checkcommon']:
                    for subtld in self.opts['commontlds']:
                        subDomain = keyword + "." + subtld + "." + tld 

                        if self.checkForStop():
                            return None

                        if self.opts['skipwildcards'] and sf.checkDnsWildcard(subtld+"."+tld):
                            pass   
                        else:
                            if len(targetList) <= self.opts['maxthreads']:
                                targetList.append(subDomain)
                            else:
                                self.tryTldWrapper(targetList)
                                targetList = list()

        # Scan whatever may be left over.
        if len(targetList) > 0:
            self.tryTldWrapper(targetList)

        return None

# End of sfp_searchtld class
