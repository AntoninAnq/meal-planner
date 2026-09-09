"""Operator commands: who may act, and how much they may spend.

**These functions now have HTTP endpoints too** (`app/routers/admin.py`), and
this module's own history is the argument for why that took so long. It used to
say a command line was deliberate: the three things an operator needs — see who
is on the instance, cut off an abuser, cap a suspected bot — are rare and
urgent, which a shell covers at no cost, while a back office is a role, an
authorisation on every route and a UI, all of it reachable from the internet to
serve one person.

Two of those premises stopped holding. A second person needed it, once helpers
were recruited to retag the catalogue; and granting THEM access stopped being
rare. The endpoints are `CurrentOwner`, which is the line the change draws:
acting on people is not what a contributor was invited for.

What did not change is where the logic lives. `actions` stays the single
implementation, called by the CLI and by the router alike — these are the verbs
reached for on a bad night, and two implementations means the one that diverges
is the one nobody exercised. The command line also stays the only way to create
the first owner, and the only way back if the last one is ever lost.
"""
