# Minimal shell-builder image for assembling sparse MBR + exFAT card images.
#
# Build context is the repository root:
#   docker build -t sbc-imager-builder:local .
#
# Invocation contract:
#   docker run --rm --privileged -e HOST_UID -e HOST_GID \
#     -v <payload>:/payload:ro -v <dist>:/out \
#     sbc-imager-builder:local /payload /out/<device>.img <size_mib> <label>
FROM debian:bookworm-slim

# fdisk provides sfdisk; util-linux provides losetup/mount/umount; exfatprogs
# provides mkfs.exfat/fsck.exfat; rsync copies the staged payload; coreutils
# provides truncate/chown/sync/mktemp.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        exfatprogs \
        util-linux \
        fdisk \
        rsync \
        coreutils \
    && rm -rf /var/lib/apt/lists/*

COPY container/build-image.sh /usr/local/bin/build-image
RUN chmod +x /usr/local/bin/build-image

ENTRYPOINT ["/usr/local/bin/build-image"]
