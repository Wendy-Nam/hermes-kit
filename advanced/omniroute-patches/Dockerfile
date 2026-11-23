# OmniRoute gateway patches that the kit image does not already carry.
#
# Scope: a silent-failure UI fix that is independent of the RTK envelope work
# in ../omniroute-rtk-envelope, so it is built as an overlay on top of the
# published adapter image rather than folded into that pipeline.
#
#   patch-ui.cjs  A connection that is switched off still carries `apiKeyHealth`
#       data, so the dashboard raises a permanent key warning for it. Several
#       deliberately disabled accounts train you to ignore the panel.
#
# Build:
#   docker build -t omniroute-ui-patch advanced/omniroute-patches
#
# Use it by pointing the student Compose at the result:
#   KIT_OMNIROUTE_IMAGE=<your-registry>/omniroute-ui-patch:<tag>
#
# Do NOT set that variable unless you intend to replace the pinned image for
# every student you hand this to. The pinned adapter carries the RTK envelope
# protection, the context-window reconciliation patch and the compression worker
# dependencies; this overlay only adds to it.
#
# patch-ui.cjs rewrites a minified dashboard chunk by exact anchor and throws
# when the anchor is absent, so upstream drift fails the build instead of
# shipping an image that looks patched but is not. That is deliberate.
ARG KIT_OMNIROUTE_IMAGE=ghcr.io/wendy-nam/hermes-kit:omniroute-rtk-json-3
FROM ${KIT_OMNIROUTE_IMAGE}

# Skips inactive connections when the dashboard selects which key alerts to show.
USER root
COPY patch-ui.cjs /tmp/patch-ui.cjs
RUN node /tmp/patch-ui.cjs && rm /tmp/patch-ui.cjs
# Docker has no `LABEL +=`: an unknown key is taken literally, so `io.hermes.patches+=`
# would create a label *named* "io.hermes.patches+" and querying io.hermes.patches would
# return nothing. Declare the full value in one instruction instead. The base image
# carries no io.hermes.* labels, so this is the complete list.
LABEL io.hermes.ui-health-patch="active-eligible-key-alerts-v1" \
      io.hermes.patches="rtk-envelope,context-reconcile,compression-worker-deps,ui-health"
USER node