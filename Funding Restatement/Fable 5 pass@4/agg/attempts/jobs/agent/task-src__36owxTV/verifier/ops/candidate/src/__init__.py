"""The funding-request scoring harness.

The desk scores E-Rate funding requests for whether they will be funded. This
package builds the table that scoring and evaluation both read.

    loading   read the pinned extract
    requests  turn form-version rows into one entry per funding request
    labels    read the outcome
    keys      the applicant key
    schema    what the deliverable looks like, and how it is written
    report    the local check the desk runs before asking for a release

`harness.py` is the entry point and is deliberately thin.
"""
