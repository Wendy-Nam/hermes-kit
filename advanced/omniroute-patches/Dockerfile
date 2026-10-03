# OmniRoute gateway patches that the kit image does not already carry.
#
# Scope: two silent-failure fixes that are independent of the RTK envelope work
# in ../omniroute-rtk-envelope, so they are built as an overlay on top of the
# published adapter image rather than folded into that pipeline. Folding them in
# would change `omniroute-rtk-json-3` for every student on a patch that has not
# been verified against their pinned base.
#
# Both fix something that fails quietly:
#
#   commandcode-anthropic.cjs  The gateway speaks the OpenAI chat shape; this
#       provider speaks Anthropic Messages. Without the shim the connection
#       appears in the provider list, reports healthy, and then cannot serve a
#       single request.
#   patch-ui.cjs  A connection that is switched off still carries `apiKeyHealth`
#       data, so the dashboard raises a permanent key warning for it. Several
#       deliberately disabled accounts train you to ignore the panel.
#
# Build:
#   docker build -t omniroute-cc-ui advanced/omniroute-patches
#
# Use it by pointing the student Compose at the result:
#   KIT_OMNIROUTE_IMAGE=<your-registry>/omniroute-cc-ui:<tag>
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

# CommandCode speaks Anthropic Messages to its endpoint and converts to and from
# the OpenAI chat shape the gateway speaks. It only engages for `claude-*` models.
USER root
COPY commandcode-anthropic.cjs /app/hermes-commandcode-anthropic.cjs
USER node

# Skips inactive connections when the dashboard selects which key alerts to show.
USER root
COPY patch-ui.cjs /tmp/patch-ui.cjs
RUN node /tmp/patch-ui.cjs && rm /tmp/patch-ui.cjs
LABEL io.hermes.ui-health-patch="active-eligible-key-alerts-v1"
LABEL io.hermes.patches+="commandcode-anthropic,ui-health"
USER node