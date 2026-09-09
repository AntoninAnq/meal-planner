"""Operator commands: who may act, and how much they may spend.

A command line and not a back office, deliberately. The three things an
operator actually needs — see who is on the instance, cut off an abuser, cap a
suspected bot — are rare and urgent, which a shell covers at no cost. A back
office is a role, an authorisation on every route, an audit trail and a UI: a
great deal of new surface, all of it reachable from the internet, to serve one
person. It becomes the right answer when a second person needs it, or when one
of these stops being rare.

Nothing here is reachable over HTTP. That is the security property worth having
while the instance is small: the most dangerous verbs in the system have no
endpoint to leave unguarded.
"""
