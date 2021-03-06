#!/usr/bin/env python
from __future__ import absolute_import, division, print_function
from datetime import datetime, timedelta
from functools import partial
from glob import glob
from hashlib import sha256
import hmac
import awssig.sigv4 as sigv4
from os.path import basename, dirname, splitext
from re import sub
from six import binary_type, iteritems, string_types
from six.moves import cStringIO, range
from string import ascii_letters, digits
from unittest import TestCase

region = "us-east-1"
service = "host"
access_key = "AKIDEXAMPLE"
secret_key = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
key_mapping = { access_key: secret_key }
remove_auth = "remove_auth"
wrong_authtype = "wrong_authtype"
clobber_sig_equals = "clobber_sig_equals"
delete_credential = "delete_credential"
delete_signature = "delete_signature"
dup_signature = "dup_signature"
delete_date = "delete_date"

# Allowed characters in quoted-printable strings
allowed_qp = ascii_letters + digits + "-_.~"

class AWSSigV4TestCaseRunner(TestCase):
    def __init__(self, filebase, tweaks="", methodName="runTest"):
        super(AWSSigV4TestCaseRunner, self).__init__(methodName=methodName)
        #if filebase == "runTest":
        #    raise ValueError()
        self.filebase = filebase
        self.tweaks = tweaks
        return
        
    def runTest(self):
        with open(self.filebase + ".sreq", "rb") as fd:
            method_line = fd.readline().strip()
            if isinstance(method_line, binary_type):
                method_line = method_line.decode("utf-8")
            headers = {}

            while True:
                line = fd.readline()
                if line in (b"\r\n", b""):
                    break

                self.assertTrue(line.endswith(b"\r\n"))
                line = line.decode("utf-8")
                header, value = line[:-2].split(":", 1)
                key = header.lower()
                value = value.strip()

                if key == "authorization":
                    if self.tweaks == remove_auth:
                        continue
                    elif self.tweaks == wrong_authtype:
                        value = "XX" + value
                    elif self.tweaks == clobber_sig_equals:
                        value = value.replace("Signature=", "Signature")
                    elif self.tweaks == delete_credential:
                        value = value.replace("Credential=", "Foo=")
                    elif self.tweaks == delete_signature:
                        value = value.replace("Signature=", "Foo=")
                    elif self.tweaks == dup_signature:
                        value += ", Signature=foo"
                elif key == "date":
                    if self.tweaks == delete_date:
                        continue
                
                if key in headers:
                    headers[key].append(value)
                else:
                    headers[key] = [value]

            headers = dict([(key, ",".join(sorted(values)))
                            for key, values in iteritems(headers)])
            body = fd.read()

            first_space = method_line.find(" ")
            second_space = method_line.find(" ", first_space + 1)
            
            method = method_line[:first_space]
            uri_path = method_line[first_space + 1:second_space]

            qpos = uri_path.find("?")
            if qpos == -1:
                query_string = ""
            else:
                query_string = uri_path[qpos+1:]
                uri_path = uri_path[:qpos]

        with open(self.filebase + ".creq", "r") as fd:
            canonical_request = fd.read().replace("\r", "")

        with open(self.filebase + ".sts", "r") as fd:
            string_to_sign = fd.read().replace("\r", "")

        v = sigv4.AWSSigV4Verifier(
            method, uri_path, query_string, headers, body, region, service,
            key_mapping, None)

        if self.tweaks:
            try:
                v.verify()
                self.fail("Expected verify() to throw an InvalidSignature "
                          "error")
            except sigv4.InvalidSignatureError:
                pass
        else:
            self.assertEqual(
                v.canonical_request, canonical_request,
                "Canonical request mismatch in %s\nExpected: %r\nReceived: %r" %
                (self.filebase, canonical_request, v.canonical_request))
            self.assertEqual(
                v.string_to_sign, string_to_sign,
                "String to sign mismatch in %s\nExpected: %r\nReceived: %r" %
                (self.filebase, string_to_sign, v.string_to_sign))
            v.verify()

        return
    # end runTest

    def __str__(self):
        return "AWSSigV4TestCaseRunner: %s" % basename(self.filebase)
# end AWSSigV4TestCaseRunner

class QuerySignatures(TestCase):
    def runTest(self):
        tests = [
            {
                'method': "GET",
                'url': "/?foo=bar",
                'body': b"",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["host"],
                'headers': {
                    'host': "host.us-east-1.amazonaws.com",
                },
            },
            {
                'method': "GET",
                'url': "/?foo=bar&&baz=yay",
                'body': b"",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["host"],
                'headers': {
                    'host': "host.us-east-1.amazonaws.com",
                },
            },
            {
                'method': "POST",
                'url': "////",
                'body': b"foo=bar",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["content-type", "host"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                }
            },
            {
                'method': "POST",
                'url': "/",
                'body': b"foo=bar",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["content-type", "host"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                },
                'quote_chars': True
            },
            {
                'method': "GET",
                'url': "/?foo=bar",
                'body': b"",
                'timestamp': datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
                'signed_headers': ["host"],
                'headers': {
                    'host': "host.us-east-1.amazonaws.com",
                },
                'timestamp_mismatch': 120,
            },
        ]

        bad = [
            {
                'method': "POST",
                'url': "////",
                'body': b"foo=bar",
                'timestamp': "20151007T231257Z",
                # Decanonicalized signed-headers
                'signed_headers': ["host", "content-type"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                }
            },
            {
                'method': "POST",
                'url': "////",
                'body': b"foo=bar",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["content-type", "host"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                },
                # Invalid credential scope format
                'scope': "foo"
            },
            {
                'method': "POST",
                # Bad path encoding
                'url': "/%zz",
                'body': b"foo=bar",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["content-type", "host"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                },
            },
            {
                'method': "POST",
                # Relative path
                'url': "../foo",
                'body': b"foo=bar",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["content-type", "host"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                },
            },
            {
                'method': "POST",
                # Go up too far.
                'url': "/a/b/../../..",
                'body': b"foo=bar",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["content-type", "host"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                },
            },
            {
                'method': "POST",
                'url': "////",
                'body': b"foo=bar",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["content-type", "host"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                },
                # Incorrect region
                'scope': (access_key + "/20151007/x-foo-bar/" + service +
                          "/aws4_request")
            },
            {
                'method': "POST",
                'url': "////",
                'body': b"foo=bar",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["content-type", "host"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                },
                # Incorrect date
                'scope': (access_key + "/20151008/" + region + "/" + service +
                          "/aws4_request")
            },
            {
                'method': "POST",
                'url': "////",
                # Invalid percent encoding
                'body': b"foo=%zz",
                'timestamp': "20151007T231257Z",
                'signed_headers': ["content-type", "host"],
                'headers': {
                    'host': "host.example.com",
                    'content-type': "application/x-www-form-urlencoded; charset=UTF-8",
                },
                'fix_qp': False
            },
            {
                'method': "GET",
                'url': "/?foo=bar",
                'body': b"",
                # Old
                'timestamp': ((datetime.utcnow() - timedelta(0, 400))
                              .strftime("%Y%m%dT%H%M%SZ")),
                'signed_headers': ["host"],
                'headers': {
                    'host': "host.us-east-1.amazonaws.com",
                },
                'timestamp_mismatch': 120,
            },
            {
                'method': "GET",
                'url': "/?foo=bar",
                'body': b"",
                # Bad format
                'timestamp': "20151008T999999Z",
                'signed_headers': ["host"],
                'headers': {
                    'host': "host.us-east-1.amazonaws.com",
                },
            },
        ]
            
        for test in tests:
            self.verify(**test)

        for test in bad:
            try:
                self.verify(bad=True, **test)
                self.fail("Expected test to fail: %r" % test)
            except sigv4.InvalidSignatureError:
                if test.get('signature') == "skip":
                    raise
                pass

        return
    
    def verify(self, method, url, body, timestamp, headers, signed_headers,
               timestamp_mismatch=None, bad=False, scope=None,
               quote_chars=False, fix_qp=True):
        date = timestamp[:8]
        credential_scope = "/".join([date, region, service, "aws4_request"])

        if scope is None:
            scope = access_key + "/" + credential_scope
        if "?" in url:
            uri, query_string = url.split("?", 1)
        else:
            uri = url
            query_string = ""

        uri = sub("//+", "/", uri)

        query_params = [
            "X-Amz-Algorithm=AWS4-HMAC-SHA256",
            "X-Amz-Credential=" + scope,
            "X-Amz-Date=" + timestamp,
            "X-Amz-SignedHeaders=" + ";".join(signed_headers)]
        
        if query_string:
            query_params.extend(query_string.split("&"))

        def fixup_qp(qp):
            result = cStringIO()
            key, value = qp.split("=", 1)
            for c in value:
                if c in allowed_qp:
                    result.write(c)
                else:
                    result.write("%%%02X" % ord(c))

            return key + "=" + result.getvalue()

        if fix_qp:
            canonical_query_string = "&".join(
                sorted(map(fixup_qp, [qp for qp in query_params if qp])))
        else:
            canonical_query_string = "&".join(sorted(query_params))

        canonical_headers = "".join([
            (header + ":" + headers[header] + "\n")
            for header in sorted(signed_headers)])

        canonical_req = (
            method + "\n" +
            uri + "\n" +
            canonical_query_string + "\n" +
            canonical_headers + "\n" +
            ";".join(signed_headers) + "\n" +
            sha256(body).hexdigest())

        string_to_sign = (
            "AWS4-HMAC-SHA256\n" +
            timestamp + "\n" +
            credential_scope + "\n" +
            sha256(canonical_req.encode("utf-8")).hexdigest())

        def sign(secret, value):
            return hmac.new(secret, value.encode("utf-8"), sha256).digest()

        k_date = sign(b"AWS4" + secret_key.encode("utf-8"), date)
        k_region = sign(k_date, region)
        k_service = sign(k_region, service)
        k_signing = sign(k_service, "aws4_request")
        signature = hmac.new(
            k_signing, string_to_sign.encode("utf-8"), sha256).hexdigest()

        query_params.append("X-Amz-Signature=" + signature)

        if quote_chars:
            bad_qp = []
            
            for qp in query_params:
                result = cStringIO()
                
                for c in qp:
                    if c.isalpha():
                        result.write("%%%02X" % ord(c))
                    else:
                        result.write(c)

                bad_qp.append(result.getvalue())
            query_params = bad_qp

        v = sigv4.AWSSigV4Verifier(
            method, uri, "&".join(query_params), headers, body, region,
            service, key_mapping, timestamp_mismatch)
        
        if not bad:
            self.assertEquals(v.canonical_request, canonical_req)
            self.assertEquals(v.string_to_sign, string_to_sign)
        v.verify()
        return

class BadTypeInitializer(TestCase):
    def runTest(self):
        params = ["GET", "/", "", {}, "", "", "", {}]

        for i in range(len(params)):
            if not isinstance(params[i], string_types):
                continue
            args = params[:i] + [None] + params[i+1:]
            try:
                sigv4.AWSSigV4Verifier(*args)
                self.fail("Expected TypeError")
            except TypeError:
                pass

        try:
            sigv4.AWSSigV4Verifier("GET", "/", "", {"Host": 7}, "", "",
                                   "", {})
            self.fail("Expected TypeError")
        except TypeError:
            pass

        try:
            sigv4.AWSSigV4Verifier("GET", "/", "", {0: "Foo"}, "", "",
                                   "", {})
            self.fail("Expected TypeError")
        except TypeError:
            pass

# Hide the test case class from automatic module discovery tools.
_test_classes = [AWSSigV4TestCaseRunner]
del AWSSigV4TestCaseRunner

def test_aws_suite():
    global AWSSigV4TestCaseRunner
    AWSSigV4TestCaseRunner = _test_classes[0]
    tests = []
    for filename in glob(dirname(__file__) + "/aws4_testsuite/*.req"):
        filebase = splitext(filename)[0]
        tests.append(AWSSigV4TestCaseRunner(filebase))
        tests.append(AWSSigV4TestCaseRunner(filebase, tweaks=remove_auth))
        tests.append(AWSSigV4TestCaseRunner(filebase, tweaks=wrong_authtype))
        tests.append(AWSSigV4TestCaseRunner(filebase, tweaks=clobber_sig_equals))
        tests.append(AWSSigV4TestCaseRunner(filebase, tweaks=delete_credential))
        tests.append(AWSSigV4TestCaseRunner(filebase, tweaks=delete_signature))
        tests.append(AWSSigV4TestCaseRunner(filebase, tweaks=dup_signature))
        tests.append(AWSSigV4TestCaseRunner(filebase, tweaks=delete_date))

    for i, test in enumerate(tests):
        test.runTest()

# Local variables:
# mode: Python
# tab-width: 8
# indent-tabs-mode: nil
# End:
# vi: set expandtab tabstop=8
