# This file is part of the faebryk project
# SPDX-License-Identifier: MIT

import faebryk.core.node as fabll
import faebryk.library._F as F
from faebryk.libs.smd import SMDSize


class has_package_requirements(fabll.Node):
    """
    Collection of constraints for package of module.
    """

    is_trait = fabll.Traits.MakeEdge(fabll.ImplementsTrait.MakeChild().put_on_type())
    is_immutable = fabll.Traits.MakeEdge(fabll.is_immutable.MakeChild()).put_on_type()
    size = F.Parameters.EnumParameter.MakeChild(enum_t=SMDSize)
    """Standard SMD chip size (resistors, capacitors, inductors)."""
    package_name = F.Parameters.StringParameter.MakeChild()
    """Free-form package name (e.g. `SOD-123`) for parts without an SMDSize."""

    def get_sizes(self) -> list[SMDSize]:
        return self.size.get().force_extract_superset().get_values_typed(SMDSize)

    def try_get_sizes(self) -> list[SMDSize] | None:
        """SMD sizes if constrained, else None (no fallback to the full domain)."""
        lit = (
            self.size.get()
            .is_parameter_operatable.get()
            .try_extract_superset(lit_type=F.Literals.AbstractEnums)
        )
        if lit is None:
            return None
        return lit.get_values_typed(SMDSize)

    def try_get_package_names(self) -> list[str] | None:
        """Free-form package names if constrained, else None."""
        lit = self.package_name.get().try_extract_superset()
        if lit is None:
            return None
        return list(F.Literals.Strings.bind_instance(lit.instance).get_values())

    @classmethod
    def MakeChild(  # type: ignore[invalid-method-override]
        cls,
        size: SMDSize | str | None = None,
        package_name: str | None = None,
    ):
        """
        Constrain the package either by SMD `size` (an SMDSize member or its
        name) or by a free-form `package_name` string. Exactly one is required.
        """
        if (size is None) == (package_name is None):
            from atopile.compiler import DslException

            raise DslException(
                "has_package_requirements needs exactly one of 'size' or 'package_name'"
            )
        out = fabll._ChildField(cls)
        if package_name is not None:
            out.add_dependant(
                F.Literals.Strings.MakeChild_SetSuperset(
                    [out, cls.package_name], package_name
                )
            )
            return out
        # Accept string from ato template syntax and convert to enum
        if isinstance(size, str):
            try:
                size = SMDSize[size]
            except KeyError:
                from atopile.compiler import DslException

                raise DslException(
                    f"Invalid value for template arguments 'size' "
                    f"for has_package_requirements: '{size}'"
                )
        assert size is not None
        out.add_dependant(
            F.Literals.AbstractEnums.MakeChild_SetSuperset(
                [out, cls.size],
                size,
            )
        )
        return out
