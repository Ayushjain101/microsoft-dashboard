"""Generate unique mailbox identities for room mailboxes.

Adapted from api-scripts/name_generator.py — as-is.
"""

import random

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Lisa", "Daniel", "Nancy",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
    "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
    "Kenneth", "Carol", "Kevin", "Amanda", "Brian", "Dorothy", "George", "Melissa",
    "Timothy", "Deborah", "Ronald", "Stephanie", "Edward", "Rebecca", "Jason", "Sharon",
    "Jeffrey", "Laura", "Ryan", "Cynthia", "Jacob", "Kathleen", "Gary", "Amy",
    "Nicholas", "Angela", "Eric", "Shirley", "Jonathan", "Anna", "Stephen", "Brenda",
    "Larry", "Pamela", "Justin", "Emma", "Scott", "Nicole", "Brandon", "Helen",
    "Benjamin", "Samantha", "Samuel", "Katherine", "Raymond", "Christine", "Gregory", "Debra",
    "Frank", "Rachel", "Alexander", "Carolyn", "Patrick", "Janet", "Jack", "Catherine",
    "Dennis", "Maria", "Jerry", "Heather", "Tyler", "Diane", "Aaron", "Ruth",
    "Jose", "Julie", "Adam", "Olivia", "Nathan", "Joyce", "Henry", "Virginia",
    "Peter", "Victoria", "Zachary", "Kelly", "Douglas", "Lauren", "Harold", "Christina",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill",
    "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell",
    "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales",
]


def generate_mailbox_identities(count: int, domain: str, tenant_short: str) -> list[dict]:
    rng = random.Random(42)
    pairs: set[tuple[str, str]] = set()
    while len(pairs) < count:
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        if (first, last) not in pairs:
            pairs.add((first, last))

    identities = []
    for i, (first, last) in enumerate(sorted(pairs), start=1):
        alias = f"{first.lower()}.{last.lower()}"
        identities.append({
            "first_name": first,
            "last_name": last,
            "display_name": f"{first} {last}",
            "alias": alias,
            "email": f"{alias}@{domain}",
            "password": f"{tenant_short}@Iced#{i:04d}",
        })
    return identities


def _generate_alias_variations(first: str, last: str) -> list[str]:
    """Generate 60+ unique email alias variations from a first/last name pair.

    No numeric suffixes — purely alphabetic combinations using truncations,
    dot separators, underscores, and reversed order.
    """
    f = first.lower()
    l = last.lower()  # noqa: E741
    seen: set[str] = set()
    variations: list[str] = []

    def _add(alias: str) -> None:
        if len(alias) >= 2 and alias not in seen:
            seen.add(alias)
            variations.append(alias)

    # Standard: f.l, fl, f.l[0], fl[0], f[0].l, f[0]l, f[0].l[0], f[0]l[0]
    _add(f"{f}.{l}")
    _add(f"{f}{l}")
    _add(f"{f}.{l[0]}")
    _add(f"{f}{l[0]}")
    _add(f"{f[0]}.{l}")
    _add(f"{f[0]}{l}")
    _add(f"{f[0]}.{l[0]}")
    _add(f"{f[0]}{l[0]}")

    # Reversed: l.f, lf, l.f[0], lf[0], l[0].f, l[0]f, l[0].f[0], l[0]f[0]
    _add(f"{l}.{f}")
    _add(f"{l}{f}")
    _add(f"{l}.{f[0]}")
    _add(f"{l}{f[0]}")
    _add(f"{l[0]}.{f}")
    _add(f"{l[0]}{f}")
    _add(f"{l[0]}.{f[0]}")
    _add(f"{l[0]}{f[0]}")

    # First truncations × last: ay.baldota, ayu.baldota, ayus.baldota
    for i in range(2, len(f)):
        _add(f"{f[:i]}.{l}")
        _add(f"{f[:i]}{l}")
        _add(f"{f[:i]}.{l[0]}")
        _add(f"{f[:i]}{l[0]}")

    # First × last truncations: ayush.ba, ayush.bal, ...
    for i in range(2, len(l)):
        _add(f"{f}.{l[:i]}")
        _add(f"{f}{l[:i]}")
        _add(f"{f[0]}.{l[:i]}")
        _add(f"{f[0]}{l[:i]}")

    # Cross truncations: ay.ba, ay.bal, ayu.ba, ayu.bal, ...
    for fi in range(2, len(f)):
        for li in range(2, len(l)):
            _add(f"{f[:fi]}.{l[:li]}")
            _add(f"{f[:fi]}{l[:li]}")

    # Reversed truncations
    for i in range(2, len(l)):
        _add(f"{l[:i]}.{f}")
        _add(f"{l[:i]}{f}")
        _add(f"{l[:i]}.{f[0]}")
        _add(f"{l[:i]}{f[0]}")

    for i in range(2, len(f)):
        _add(f"{l}.{f[:i]}")
        _add(f"{l}{f[:i]}")

    for li in range(2, len(l)):
        for fi in range(2, len(f)):
            _add(f"{l[:li]}.{f[:fi]}")
            _add(f"{l[:li]}{f[:fi]}")

    # Extras with underscores and standalone
    _add(f)
    _add(l)
    _add(f"{f}_{l}")
    _add(f"{l}_{f}")

    return variations


def generate_custom_identities(
    names: list[str], count: int, domain: str, tenant_short: str
) -> list[dict]:
    """Generate identities using custom names with unique alias variations.

    Args:
        names: List of "First Last" strings.
        count: Total number of mailboxes to create.
        domain: Email domain.
        tenant_short: Tenant name for password generation.

    Returns:
        List of identity dicts in the same format as generate_mailbox_identities.

    Raises:
        ValueError: If not enough unique variations can be generated.
    """
    n = len(names)
    per_name = count // n
    remainder = count % n

    identities: list[dict] = []
    all_aliases: set[str] = set()
    idx = 0

    for i, name in enumerate(names):
        parts = name.strip().split()
        if len(parts) < 2:
            raise ValueError(f"Each name must have first and last: '{name}'")
        first = parts[0]
        last = parts[-1]

        needed = per_name + (1 if i < remainder else 0)
        variations = _generate_alias_variations(first, last)

        # Filter out any aliases already used by other names
        available = [v for v in variations if v not in all_aliases]
        if len(available) < needed:
            raise ValueError(
                f"Not enough unique variations for '{name}': need {needed}, "
                f"got {len(available)}. Use fewer mailboxes per name or longer names."
            )

        for alias in available[:needed]:
            idx += 1
            all_aliases.add(alias)
            identities.append({
                "first_name": first,
                "last_name": last,
                "display_name": f"{first} {last}",
                "alias": alias,
                "email": f"{alias}@{domain}",
                "password": f"{tenant_short}@Iced#{idx:04d}",
            })

    return identities
