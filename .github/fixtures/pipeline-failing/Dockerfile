# A pipeline whose check fails: the positive control for "evidence survives a
# failing step".
#
# The point is not that the build goes red. It is that the build goes GREEN --
# an image exists, and the failure is readable inside it. A step that failed the
# build would leave nothing to read, which is the defect the real pipeline
# exists to remove; a check that only asserts "the workflow failed" would pass
# whether or not the evidence survived.
FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

ENV EVIDENCE_DIR=/evidence

COPY pipeline/ /pipeline/

# Fails, loudly, and must not fail the build.
RUN /pipeline/record will-fail sh -c 'echo "the check ran and did not like what it found"; exit 3'

# A phase that is declared and never runs at all, so one image exercises both
# refusals: a recorded failure, and an absence.
RUN printf 'phases:\n  - id: will-fail\n  - id: never-ran\n' > /pipeline/phases.yaml

CMD ["/pipeline/refuse"]
