# Base image pinned by digest. Resolve with:
#   docker buildx imagetools inspect python:3.12-slim-bookworm
# Index digest for python:3.12-slim-bookworm (resolved 2026-10-19):
#   sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# fdisk provides sfdisk; util-linux provides losetup/mount; exfatprogs provides
# mkfs.exfat/fsck.exfat; e2fsprogs provides the fsck/mkfs family used by tests.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        e2fsprogs=1.47.0-2+b2 \
        exfatprogs=1.2.0-1+deb12u1 \
        util-linux=2.38.1-5+deb12u3 \
        fdisk=2.38.1-5+deb12u3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

CMD ["python", "-m", "sbc_imager.assembler", "--help"]
