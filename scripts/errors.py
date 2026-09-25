class BoundaryError(ValueError):
    """A path crosses the read-only source/output boundary."""


class ContractError(ValueError):
    """A payload does not satisfy the frozen batch-0 contract."""


class DuplicateMaterialError(ContractError):
    """A platform emitted the same material identity more than once."""
