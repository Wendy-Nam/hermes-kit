ARG OMNIROUTE_BASE_IMAGE=diegosouzapw/omniroute:next-web@sha256:3c8698a83d40205914aa9e343fd3b1378c4ba8940a3a3adb5ecfc7f0b1b9cb61
FROM ${OMNIROUTE_BASE_IMAGE}
USER root
COPY envelope.cjs /app/hermes-rtk-envelope.cjs
COPY patch.cjs /tmp/patch-hermes-rtk.cjs
RUN node /tmp/patch-hermes-rtk.cjs && rm /tmp/patch-hermes-rtk.cjs
USER node
