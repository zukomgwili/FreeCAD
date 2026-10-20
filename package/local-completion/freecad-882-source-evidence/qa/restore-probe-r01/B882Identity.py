"""Transparent custom-suite registration; original identity bytes stay exact."""
import AppYzkIdentity as original

original.CUSTOM_SUITES.add('B882Profile')
AppNativeIdentity = original.AppNativeIdentity
