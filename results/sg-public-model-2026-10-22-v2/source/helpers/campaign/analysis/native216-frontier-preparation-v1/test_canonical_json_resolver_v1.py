"""Synthetic-only /tmp fixtures. No campaign reads or actual acceptance claim."""
import contextlib
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

import canonical_json_resolver_v1 as c


def pin(path,data):
    return {"path":str(path),"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)}


@contextlib.contextmanager
def fixture_reader(path):
    # Synthetic stand-in for the separately qualified storage.regular_reader.
    if path.resolve(strict=False)!=path:raise ValueError("symlink refused")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:raise ValueError("not unique regular fixture")
        yield stream,before
        after=os.fstat(stream.fileno());current=os.lstat(path)
        fields=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        if fields(before)!=fields(after) or fields(before)!=fields(current):raise ValueError("changed fixture")


class Base:
    def __init__(self):self.bindings={}
    def read_path(self,path,expected_sha=None):
        with fixture_reader(Path(path)) as (stream,_):data=stream.read()
        digest=hashlib.sha256(data).hexdigest()
        if expected_sha is not None and digest!=expected_sha:raise ValueError("base SHA mismatch")
        self.bindings[path]=digest
        return json.loads(data)
    def read_ref(self,value):
        result=self.read_path(value["path"],expected_sha=value["sha256"])
        if "bytes" in value and Path(value["path"]).stat().st_size!=value["bytes"]:raise ValueError("base size mismatch")
        return result


class CanonicalTransport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="native216-resolver-fixture-",dir="/tmp")
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def fixture(self,raw=b'{"native":"same","values":[1,2]}\n',present=False,mutator=None):
        rawpath=self.root/"summary.json";archive=self.root/"summary.json.gz";manifest=self.root/"summary.json.archive.json"
        zipped=gzip.compress(raw,mtime=0)
        if mutator:zipped=mutator(zipped)
        archive.write_bytes(zipped)
        if present:rawpath.write_bytes(raw)
        entry={"raw":pin(rawpath,raw),"archive":pin(archive,zipped),"manifest":{}}
        self.rewrite_manifest(entry,manifest)
        return entry,Base()

    def rewrite_manifest(self,entry,path=None,overrides=None):
        raw,archive=entry["raw"],entry["archive"]
        value={"schema":"prospective-lossless-storage-v1","kind":"immutable-lossless-archive-manifest",
            "raw_path":raw["path"],"raw_sha256":raw["sha256"],"raw_bytes":raw["bytes"],
            "archive_path":archive["path"],"gzip_sha256":archive["sha256"],"gzip_bytes":archive["bytes"],
            "reconstruction_verified_sha256":raw["sha256"],"reconstruction_verified_bytes":raw["bytes"]}
        value.update(overrides or {})
        path=path or Path(entry["manifest"]["path"])
        data=json.dumps(value).encode();path.write_bytes(data);entry["manifest"]=pin(path,data)

    def resolver(self,entry,base=None,limit=1024*1024):
        return c.CanonicalJSONResolver(base or Base(),[entry],fixture_reader,limit)

    def test_retired_exact_bytes_decode_without_restore(self):
        entry,base=self.fixture();resolver=self.resolver(entry,base)
        self.assertEqual(resolver.read_path(entry["raw"]["path"]),{"native":"same","values":[1,2]})
        self.assertFalse(Path(entry["raw"]["path"]).exists())
        self.assertEqual(resolver.bindings[entry["raw"]["path"]],entry["raw"]["sha256"])
        self.assertTrue(resolver.transport_bindings[entry["raw"]["path"]]["full_eof_crc_and_raw_identity_verified"])

    def test_declared_archive_guard_is_not_filesystem_exists(self):
        entry,base=self.fixture();resolver=self.resolver(entry,base)
        self.assertTrue(resolver.is_approved_archive_path(entry["raw"]["path"]))
        self.assertFalse(Path(entry["raw"]["path"]).exists())
        self.assertFalse(resolver.is_approved_archive_path(str(self.root/"not-approved.json")))

    def test_present_exact_raw_same_document(self):
        entry,base=self.fixture(present=True);resolver=self.resolver(entry,base)
        self.assertEqual(resolver.read_ref(entry["raw"]),{"native":"same","values":[1,2]})
        self.assertEqual(resolver.transport_bindings[entry["raw"]["path"]]["transport"],"exact-present-raw")

    def test_file_ref_keeps_logical_raw_identity(self):
        entry,base=self.fixture();self.assertEqual(self.resolver(entry,base).file_ref(entry["raw"]["path"]),entry["raw"])

    def test_present_bad_raw_never_uses_valid_archive(self):
        entry,base=self.fixture(present=True);Path(entry["raw"]["path"]).write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError,"fallback refused"):self.resolver(entry,base).read_ref(entry["raw"])

    def test_expected_sha_must_equal_A_raw(self):
        entry,base=self.fixture()
        with self.assertRaisesRegex(ValueError,"requested SHA"):self.resolver(entry,base).read_path(entry["raw"]["path"],expected_sha="0"*64)

    def test_consuming_ref_size_must_equal_A_raw(self):
        entry,base=self.fixture();wrong=dict(entry["raw"],bytes=1)
        with self.assertRaisesRegex(ValueError,"consuming canonical ref"):self.resolver(entry,base).read_ref(wrong)

    def test_current_gzip_hash_checked(self):
        entry,base=self.fixture();path=Path(entry["archive"]["path"]);data=bytearray(path.read_bytes());data[5]^=1;path.write_bytes(data)
        with self.assertRaisesRegex(ValueError,"current gzip SHA"):self.resolver(entry,base).read_ref(entry["raw"])

    def test_crc_rejected_even_with_current_compressed_pin(self):
        def corrupt(value):
            data=bytearray(value);data[-8]^=1;return bytes(data)
        entry,base=self.fixture(mutator=corrupt)
        with self.assertRaises(gzip.BadGzipFile):self.resolver(entry,base).read_ref(entry["raw"])

    def test_truncated_member_rejected_after_current_pin(self):
        entry,base=self.fixture(mutator=lambda value:value[:-3])
        with self.assertRaises(EOFError):self.resolver(entry,base).read_ref(entry["raw"])

    def test_raw_sha_checked_after_full_eof(self):
        entry,base=self.fixture();entry["raw"]["sha256"]="0"*64;self.rewrite_manifest(entry)
        with self.assertRaisesRegex(ValueError,"full reconstruction SHA"):self.resolver(entry,base).read_ref(entry["raw"])

    def test_exact_raw_length_limits_decompression(self):
        entry,base=self.fixture();entry["raw"]["bytes"]=1;self.rewrite_manifest(entry)
        with self.assertRaisesRegex(ValueError,"exact accepted raw bound"):self.resolver(entry,base).read_ref(entry["raw"])

    def test_manifest_cannot_redirect_approved_archive(self):
        entry,base=self.fixture();self.rewrite_manifest(entry,overrides={"archive_path":"/tmp/unapproved.gz"})
        with self.assertRaisesRegex(ValueError,"manifest/A/approved gzip"):self.resolver(entry,base).read_ref(entry["raw"])

    def test_manifest_bytes_pinned_before_json(self):
        entry,base=self.fixture();Path(entry["manifest"]["path"]).write_text("{}")
        with self.assertRaisesRegex(ValueError,"raw-present bytes differ"):self.resolver(entry,base).read_ref(entry["raw"])

    def test_unapproved_missing_path_has_no_archive_search(self):
        entry,base=self.fixture()
        with self.assertRaises(FileNotFoundError):self.resolver(entry,base).read_path(str(self.root/"not-approved.json"))

    def test_unapproved_regular_json_uses_unchanged_base(self):
        entry,base=self.fixture();path=self.root/"query-metadata.json";path.write_text('{"x":1}')
        self.assertEqual(self.resolver(entry,base).read_path(str(path)),{"x":1})

    def test_manifest_cap_checked_before_read(self):
        entry,base=self.fixture()
        with self.assertRaisesRegex(ValueError,"memory bound"):self.resolver(entry,base,limit=1)

    def test_duplicate_or_alias_mappings_rejected(self):
        entry,base=self.fixture()
        with self.assertRaisesRegex(ValueError,"duplicate canonical"):c.CanonicalJSONResolver(base,[entry,entry],fixture_reader,1024*1024)

    def test_noncanonical_ref_path_rejected(self):
        entry,base=self.fixture();entry["raw"]["path"]=str(self.root)+"//summary.json"
        with self.assertRaisesRegex(ValueError,"noncanonical"):self.resolver(entry,base)

    def test_present_symlink_never_falls_back(self):
        entry,base=self.fixture();target=self.root/"target.json";target.write_text("{}");Path(entry["raw"]["path"]).symlink_to(target)
        with self.assertRaisesRegex(ValueError,"symlink"):self.resolver(entry,base).read_ref(entry["raw"])

    def test_json_decoder_unchanged_and_after_crc(self):
        entry,base=self.fixture(raw=b"not json")
        with self.assertRaises(json.JSONDecodeError):self.resolver(entry,base).read_ref(entry["raw"])

    def test_existing_canonical_binding_cannot_change(self):
        entry,base=self.fixture();base.bindings[entry["raw"]["path"]]="0"*64
        with self.assertRaisesRegex(ValueError,"identity changed"):self.resolver(entry,base).read_ref(entry["raw"])


if __name__=="__main__":unittest.main()
