#!/usr/bin/env python3

import sys
import time

from beamtimedb import BeamtimeDB
from beamtimedb.orcid_lookup import find_orcid


def main():
    db = BeamtimeDB()
    all_users = db.get_users()
    if not all_users:
        print("No users found in the database.")
        sys.exit(0)

    missing = [u for u in all_users if not u.orcid]
    print(f"Total users: {len(all_users)}  |  Missing ORCID: {len(missing)}")

    updated = []
    not_found = []
    skipped = []

    for user in missing:
        last = (user.last_name or "").strip()
        first = (user.first_name or "").strip()
        email = (user.email or "").strip()

        if not last or not first:
            skipped.append((user, "missing name"))
            print(f"  SKIP  id={user.id} : no full name")
            continue

        affiliation = None
        if user.affiliation_id:
            inst = db.get_row("institution", where={"id": user.affiliation_id})
            if inst:
                affiliation = inst.name

        label = f"{first} {last}"
        if affiliation:
            label += f" / {affiliation}"
        print(f"  Search: {label} ...", end=" ", flush=True)

        orcid = find_orcid(last, first, email=email or None, affiliation=affiliation)

        if orcid:
            db.update("person", where={"id": user.id}, orcid=orcid)
            updated.append((user, orcid))
            print(f"found  {orcid}")
        else:
            not_found.append(user)
            print("not found / ambiguous")

        time.sleep(0.1)

    print(f"\n--- Summary ---")
    print(f"  Updated : {len(updated)}")
    print(f"  Not found : {len(not_found)}")
    print(f"  Skipped (no name) : {len(skipped)}")

    if updated:
        print("\nUpdated users:")
        for u, o in updated:
            print(f"  {u.first_name} {u.last_name:30s}  {o}")

    if not_found:
        print("\nNeeds manual review (0 or multiple ORCID matches):")
        for u in not_found:
            print(f"  {u.first_name} {u.last_name}")


if __name__ == "__main__":
    main()

