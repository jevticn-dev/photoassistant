"""FastAPI service layer.

A thin wrapper around the ``photoassistant`` library: routes validate input, call
the library and map the output. **Logic does not live in a route.**

The service is **internal** — reachable by the .NET API only, never by a browser.
It knows nothing about users: no authentication, no ``user_id`` in domain logic,
no authorisation. Data ownership and access control belong to the .NET API, which
is the only publicly reachable component (ADR-8).
"""
