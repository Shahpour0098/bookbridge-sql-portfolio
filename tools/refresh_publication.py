"""Refresh the actual PDF delivery manifest and optionally create a new ZIP.

The default is read-only. --write updates only the three generated records at the
selected source root. --zip additionally creates a new archive and external hash;
it never overwrites an archive or copies Git metadata or private runtime data.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
from datetime import datetime,timezone

import package_delivery as package

GENERATED={"MANIFEST.json","PACKAGE_CHECK.json","SHA256SUMS.txt"}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write",action="store_true")
    parser.add_argument("--zip",type=Path)
    parser.add_argument("--secret-source",type=Path,help="Optional original private project root; read-only password leak check, never copied.")
    parser.add_argument("--inventory-out",type=Path)
    args=parser.parse_args()
    root=args.root.resolve()
    if not root.is_dir():raise ValueError("Source root is not a directory")
    archive=args.zip.resolve() if args.zip else None
    if archive:
        if not args.write:raise ValueError("--zip requires --write")
        if archive.suffix.lower()!=".zip" or archive.parent not in {root,root.parent}:
            raise ValueError("Archive must be a ZIP directly in the source root or its parent")
        if archive.exists() or archive.with_suffix(".zip.sha256").exists():
            raise ValueError("Archive or archive checksum already exists; nothing overwritten")
    items,missing=package.read_selection(root,[])
    check=package.validate(items,root,missing)
    if check["status"]!="passed":raise ValueError("Selection validation failed: "+json.dumps(check,ensure_ascii=False))
    if args.secret_source:
        values=package.known_private_values(args.secret_source.resolve())
        leaks=[]
        for item in items:
            if any(secret in part for part in package.content_parts(package.payload(item),Path(item["destination"]).suffix.lower()) for secret in values):
                leaks.append(item["destination"])
        if leaks:raise ValueError("Known private value found; publication refused: "+", ".join(leaks))
        check["external_known_password_values_checked"]=len(values)
        check["external_known_password_leaks"]=[]
    # Verify every relative README file link in this current delivery.
    destinations={item["destination"] for item in items}
    unresolved=[]
    for item in items:
        if Path(item["destination"]).name!="README.md":continue
        parent=Path(item["destination"]).parent
        for raw in re.findall(r"\]\(([^)]+)\)",package.payload(item).decode("utf-8-sig")):
            target=raw.strip("<>").split("#",1)[0]
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:",target,re.I):continue
            full=(root/parent/target).resolve()
            if not full.is_relative_to(root):unresolved.append(item["destination"]+" -> "+target);continue
            rel=full.relative_to(root).as_posix()
            if rel not in destinations and not any(n.startswith(rel.rstrip("/")+"/") for n in destinations):
                unresolved.append(item["destination"]+" -> "+target)
    if unresolved:raise ValueError("Unresolved README links: "+json.dumps(unresolved,ensure_ascii=False))
    check["all_readme_relative_links_checked"]=True
    check["unresolved_readme_links"]=[]
    check["pdf_delivery"]=True
    entries=[]
    for item in items:
        path=item["destination"]
        actual=root/path
        if not actual.is_file():raise ValueError("Refresh requires an already-numbered source layout: "+path)
        raw=package.payload(item)
        if raw!=actual.read_bytes():raise ValueError("README transformation pending; apply it before in-place refresh: "+path)
        entries.append({"path":path,"bytes":len(raw),"sha256":package.sha(raw),"source":path})
    result={"status":"passed","source_root":str(root),"selected_source_files":len(entries),"selection":check,"write_requested":args.write,"archive_requested":str(archive) if archive else None}
    if args.write:
        manifest={"project":"BookBridge","delivery_date":"2026-11-02","source_files":entries,"generated_files":sorted(GENERATED),"manifest_scope":"Every selected source including all delivered PDFs and publication tools. Generated manifest/check records are verified by SHA256SUMS. SHA256SUMS excludes only itself; ZIP checksum is external. Git metadata is excluded.","refreshed_at":datetime.now(timezone.utc).isoformat()}
        (root/"MANIFEST.json").write_bytes(package.json_bytes(manifest))
        (root/"PACKAGE_CHECK.json").write_bytes(package.json_bytes(check))
        names=sorted(destinations|{"MANIFEST.json","PACKAGE_CHECK.json"})
        lines=[package.sha((root/name).read_bytes())+"  "+name for name in names]
        (root/"SHA256SUMS.txt").write_text("\n".join(lines)+"\n",encoding="utf-8",newline="\n")
        for line in lines:
            digest,name=line.split("  ",1)
            if package.sha((root/name).read_bytes())!=digest:raise RuntimeError("Checksum verification failed")
        result["verified_checksums"]=len(lines)
        result["delivery_files"]=len(names)+1
        if archive:
            archive_names=sorted(destinations|GENERATED)
            prefix=archive.stem
            with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
                for name in archive_names:
                    info=zipfile.ZipInfo(prefix+"/"+name,package.FIXED_ZIP_TIME)
                    info.compress_type=zipfile.ZIP_DEFLATED
                    info.create_system=3
                    info.external_attr=0o100644<<16
                    z.writestr(info,(root/name).read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
            digest=package.sha(archive.read_bytes())
            archive.with_suffix(".zip.sha256").write_text(digest+"  "+archive.name+"\n",encoding="utf-8",newline="\n")
            with zipfile.ZipFile(archive) as z:
                if z.testzip() is not None or len(z.namelist())!=len(archive_names):raise RuntimeError("ZIP integrity failed")
                for name in archive_names:
                    if z.read(prefix+"/"+name)!=(root/name).read_bytes():raise RuntimeError("ZIP content differs from source")
            result["archive"]={"path":str(archive),"bytes":archive.stat().st_size,"sha256":digest,"files":len(archive_names),"integrity":"passed"}
    if args.inventory_out:
        args.inventory_out.parent.mkdir(parents=True,exist_ok=True)
        args.inventory_out.write_bytes(package.json_bytes(result))
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,RuntimeError,zipfile.BadZipFile) as error:raise SystemExit("Publication refresh stopped: "+str(error)) from None
