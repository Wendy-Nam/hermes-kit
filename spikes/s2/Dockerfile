# Phase 0 spike image: upstream base (D8) + rtk (S5). Throwaway.
FROM docker.io/nousresearch/hermes-agent:v2026.9.11@sha256:9469b3e78b9545b6d576eb8887a95352e9a0ea83730eaf31431cf862ca1010e1
ARG RTK_VERSION=0.50.0
USER root
# python urllib instead of curl: the base image's tool set is not verified yet
RUN python3 - <<EOF
import hashlib, tarfile, urllib.request, shutil, os, io
base = "https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}/"
name = "rtk-x86_64-unknown-linux-musl.tar.gz"
blob = urllib.request.urlopen(base + name, timeout=60).read()
sums = urllib.request.urlopen(base + "checksums.txt", timeout=60).read().decode()
want = next(l.split()[0] for l in sums.splitlines() if l.strip().endswith(name))
assert hashlib.sha256(blob).hexdigest() == want, "rtk checksum mismatch"
with tarfile.open(fileobj=io.BytesIO(blob)) as t:
    m = next(m for m in t.getmembers() if os.path.basename(m.name) == "rtk" and m.isfile())
    with t.extractfile(m) as src, open("/usr/local/bin/rtk", "wb") as dst:
        shutil.copyfileobj(src, dst)
os.chmod("/usr/local/bin/rtk", 0o755)
EOF
RUN rtk --version
