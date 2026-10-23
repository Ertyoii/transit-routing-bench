"""Minimal read-only canonical JSON transport; candidate, not actual admission.

Wrap unchanged BoundIO with exact approved A/raw + archive-manifest + gzip refs.
The owner-qualified caller supplies the accepted mapping and already-qualified
storage.regular_reader. No archive/restore/retire operator or source is imported.
No arbitrary fallback, discovery, path aliases, raw creation, or new decoder.
Actual ancestry acceptance and resource authorization remain caller prerequisites.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path


CHUNK = 1024 * 1024


def need(value,message):
    if not value:raise ValueError(message)


def sha(value):
    return isinstance(value,str) and len(value)==64 and all(c in "0123456789abcdef" for c in value)


def ref(value):
    need(isinstance(value,dict) and {"path","sha256","bytes"} <= set(value),"complete exact byte ref required")
    need(isinstance(value["path"],str),"ref path is not a string")
    path=Path(value["path"])
    need(path.is_absolute() and value["path"]==str(path)==os.path.abspath(str(path)),"noncanonical absolute ref path")
    need(sha(value["sha256"]) and type(value["bytes"]) is int and value["bytes"]>=0,"invalid byte ref identity")
    return dict(path=str(path),sha256=value["sha256"],bytes=value["bytes"])


class CanonicalJSONResolver:
    def __init__(self,base,approved,regular_reader,max_document_bytes):
        need(type(max_document_bytes) is int and max_document_bytes>0,"explicit finite document bound required")
        self.base,self.regular_reader,self.limit=base,regular_reader,max_document_bytes
        self.bindings=base.bindings
        self.approved={}
        self.transport_bindings={}
        for entry in approved:
            need(isinstance(entry,dict) and set(entry)=={"raw","manifest","archive"},"unrequested transport entry field")
            raw,manifest,archive=(ref(entry[key]) for key in ("raw","manifest","archive"))
            need(raw["path"] not in self.approved,"duplicate canonical raw mapping")
            need(len({raw["path"],manifest["path"],archive["path"]})==3,"transport path roles alias")
            need(raw["bytes"]<=self.limit and manifest["bytes"]<=self.limit,"approved document exceeds authorized memory bound")
            self.approved[raw["path"]]={"raw":raw,"manifest":manifest,"archive":archive}
        paths=[pin["path"] for entry in self.approved.values() for pin in entry.values()]
        need(len(paths)==len(set(paths)),"transport path used in multiple roles/entries")

    def _remember(self,path,digest):
        need(path not in self.bindings or self.bindings[path]==digest,"canonical document identity changed")
        self.bindings[path]=digest

    def is_approved_archive_path(self,path):
        """Declared mapping only, NOT fabricated exists() or actual integrity."""
        return str(path) in self.approved

    def _raw_bytes(self,pin):
        need(pin["bytes"]<=self.limit,"document exceeds authorized memory bound")
        data=bytearray(); digest=hashlib.sha256()
        with self.regular_reader(Path(pin["path"])) as (stream,_):
            for block in iter(lambda:stream.read(CHUNK),b""):
                need(len(data)+len(block)<=pin["bytes"],"raw length exceeds accepted identity")
                data.extend(block);digest.update(block)
        need(len(data)==pin["bytes"] and digest.hexdigest()==pin["sha256"],"raw-present bytes differ; archive fallback refused")
        return bytes(data)

    def _manifest(self,entry):
        # Do not use a raw-path reopen after verification. Decode these exact
        # immutable bytes through the unchanged standard JSON decoder.
        pin=entry["manifest"]
        value=json.loads(self._raw_bytes(pin))
        need(isinstance(value,dict),"archive manifest is not an object")
        need(value.get("schema")=="prospective-lossless-storage-v1"
             and value.get("kind")=="immutable-lossless-archive-manifest","unaccepted archive manifest kind")
        raw,archive=entry["raw"],entry["archive"]
        expected={"raw_path":raw["path"],"raw_sha256":raw["sha256"],"raw_bytes":raw["bytes"],
            "archive_path":archive["path"],"gzip_sha256":archive["sha256"],"gzip_bytes":archive["bytes"],
            "reconstruction_verified_sha256":raw["sha256"],"reconstruction_verified_bytes":raw["bytes"]}
        need(all(value.get(key)==item for key,item in expected.items()),"archive manifest/A/approved gzip identity differs")
        self._remember(pin["path"],pin["sha256"])
        return value

    def _archive_bytes(self,entry):
        self._manifest(entry)
        raw,archive=entry["raw"],entry["archive"]
        data=bytearray();raw_digest=hashlib.sha256();compressed=hashlib.sha256();size=0
        with self.regular_reader(Path(archive["path"])) as (stream,_):
            for block in iter(lambda:stream.read(CHUNK),b""):
                size+=len(block);need(size<=archive["bytes"],"gzip length exceeds approved identity")
                compressed.update(block)
            need(size==archive["bytes"] and compressed.hexdigest()==archive["sha256"],"current gzip SHA/bytes differ")
            stream.seek(0)
            with gzip.GzipFile(fileobj=stream,mode="rb") as unzipped:
                for block in iter(lambda:unzipped.read(CHUNK),b""):
                    need(len(data)+len(block)<=raw["bytes"],"reconstruction exceeds exact accepted raw bound")
                    data.extend(block);raw_digest.update(block)
                # Full EOF is required before JSON decode; gzip validates CRC
                # and trailer and refuses malformed/truncated trailing members.
            need(len(data)==raw["bytes"] and raw_digest.hexdigest()==raw["sha256"],"full reconstruction SHA/bytes differ")
        self.transport_bindings[raw["path"]]={"transport":"exact-approved-gzip",
            "raw":dict(raw),"manifest":dict(entry["manifest"]),"archive":dict(archive),
            "full_eof_crc_and_raw_identity_verified":True}
        return bytes(data)

    def read_path(self,path,expected_sha=None):
        path=str(path)
        need(Path(path).is_absolute() and path==str(Path(path))==os.path.abspath(path),"noncanonical requested path")
        entry=self.approved.get(path)
        if entry is None:
            return self.base.read_path(path,expected_sha=expected_sha)
        pin=entry["raw"]
        need(expected_sha is None or expected_sha==pin["sha256"],"requested SHA differs from accepted canonical raw")
        try:
            os.lstat(path)
        except FileNotFoundError:
            data=self._archive_bytes(entry)
        else:
            data=self._raw_bytes(pin)  # Any error here is terminal, never fallback.
            self.transport_bindings[path]={"transport":"exact-present-raw","raw":dict(pin)}
        value=json.loads(data)
        self._remember(path,pin["sha256"])
        return value

    def read_ref(self,value):
        if isinstance(value,dict) and value.get("path") in self.approved:
            pin=self.approved[value["path"]]["raw"]
            need(value.get("sha256")==pin["sha256"] and ("bytes" not in value or value["bytes"]==pin["bytes"]),
                 "consuming canonical ref differs from accepted raw identity")
            return self.read_path(value["path"],expected_sha=value["sha256"])
        return self.base.read_ref(value)

    def file_ref(self,path):
        path=str(path)
        if path in self.approved:
            self.read_path(path)
            return dict(self.approved[path]["raw"])
        return self.base.file_ref(path)
