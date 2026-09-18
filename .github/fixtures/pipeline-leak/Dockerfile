# A deliberately leaking image: the positive control for the layer scan.
#
# The secret is written in one step and removed in the next. The final
# filesystem does not contain it; the earlier layer does, and always will. An
# image scanner that reports this image clean is a scanner whose clean verdicts
# carry no information -- which is the whole reason this fixture exists and is
# built on every run rather than described in a comment.
#
# The value below is a fabricated test credential. It is not a real key, it
# grants nothing, and it exists only to be found.
FROM alpine:3.20

RUN mkdir -p /tmp/leak \
    && printf 'aws_secret_access_key = %s\n' \
         'wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY' > /tmp/leak/credentials

RUN rm -f /tmp/leak/credentials

CMD ["/bin/true"]
