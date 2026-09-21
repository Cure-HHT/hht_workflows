# A deliberately leaking image: the positive control for the layer scan.
#
# The secret is written in one step and removed in the next. The final
# filesystem does not contain it; the earlier layer does, and always will. An
# image scanner that reports this image clean is a scanner whose clean verdicts
# carry no information -- which is why this fixture is built and scanned on
# every run rather than described in a comment.
#
# TWO THINGS ABOUT THE VALUE, both learned by getting them wrong:
#
# 1. It is assembled from halves at build time. A complete, detectable secret
#    committed here would be caught by this repository's own gitleaks hook --
#    the fixture could not be committed at all. Neither half matches a rule on
#    its own; the file the layer holds does.
#
# 2. It is NOT the AWS documentation example key. The first version of this
#    fixture used `wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY`, which gitleaks
#    allowlists by design, so the positive control reported clean on a leaking
#    image -- the exact vacuous pass this fixture exists to rule out,
#    reproduced inside the check meant to prevent it. Measured, on this
#    machine, before anything was pushed.
#
# The assembled value is fabricated, grants nothing, and exists only to be
# found. It trips the `generic-api-key` rule on entropy.
FROM alpine:3.20

ARG LEAK_HEAD=kK7nR2pQ9wZ4xV6bN8mL
ARG LEAK_TAIL=1jH5gF3dS0aY7cX2vB4e

RUN mkdir -p /tmp/leak \
    && printf 'aws_secret_access_key = %s%s\n' "${LEAK_HEAD}" "${LEAK_TAIL}" \
       > /tmp/leak/credentials

RUN rm -f /tmp/leak/credentials

CMD ["/bin/true"]
