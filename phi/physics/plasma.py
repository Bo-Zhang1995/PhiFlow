"""
Definition of plasma, HasegawaWakatani Model, as well as plasma-related functions.
"""
from numbers import Number

import numpy as np
from phi import math, struct

from phi.physics.domain import Domain, DomainState
from phi.physics.field import CenteredGrid, StaggeredGrid, advect, union_mask
from phi.physics.field.effect import Gravity, effect_applied, gravity_tensor
from phi.physics.material import OPEN, Material
from phi.physics.physics import Physics, StateDependency
from phi.physics.pressuresolver.solver_api import FluidDomain
from phi.physics.pressuresolver.sparse import SparseCG


@struct.definition()
class PlasmaHW(DomainState):
    """
    Following Hasegawa-Wakatani Model of incompressible Plasma
    A PlasmaHW state consists of:
    - Density field (centered grid)
    - Phi field (centered grid)
    - Omega field (centered grid)
    """

    def __init__(self, domain, tags=('plasma'), name='plasmaHW', **kwargs):
        DomainState.__init__(self, **struct.kwargs(locals()))
        self.nu = 1.  # nu_e/(1.96*w_ce)
        density2d = self.density.copied_with(
            data=math.reshape(self.density.data, [-1] + list(self.density.data.shape[2:])),
            box=domain.box.without_axis(0))
        _, density_grad_x = density2d.gradient().unstack()
        self.kappa = 1 / np.sum(density2d.data) * density_grad_x.data  # density_grad_x.data * (1/np.sum(density2d.data))

    @struct.variable(default=0, dependencies=DomainState.domain)
    def density(self, density):
        """
        The marker density is stored in a CenteredGrid with dimensions matching the domain.
        It describes the number of particles per physical volume.
        """
        return self.centered_grid('density', density)

    @struct.variable(default=0, dependencies=DomainState.domain)
    def phi(self, phi):
        """
        The marker phi is stored in a CenteredGrid with dimensions matching the domain.
        It describes ..... # TODO
        """
        return self.centered_grid('phi', phi)

    @struct.variable(default=0, dependencies=DomainState.domain)
    def omega(self, omega):
        """
        The marker omega is stored in a CenteredGrid with dimensions matching the domain.
        It describes ..... # TODO
        """
        return self.centered_grid('omega', omega)

    def __repr__(self):
        return "plasma[density: %s, phi: %s, omega %s]" % (self.density, self.phi, self.omega)


class HasegawaWakatani(Physics):
    r"""
    Physics modelling the Hasegawa-Wakatani equations.
    Supports buoyancy proportional to the marker density.  # TODO: Adjust
    Supports obstacles, density effects, velocity effects, global gravity.  # TODO: Adjust

    Hasegawa-Wakatani Equations:
    $$
        \partial_t \Omega = \frac{1}{\nu} \nabla_{||}^2(n-\phi) - \{\phi,\Omega\} \\
        \partial_t n = \frac{1}{\nu} \nabla^2_{||}(n-\phi) - \{\phi,n\} - \kappa_n\partial_y\phi 
    $$

    """

    def __init__(self, pressure_solver=None, conserve_density=True):
        Physics.__init__(self, [  # No effects currently supported for the fields
            #StateDependency('obstacles', 'obstacle'),
            #StateDependency('gravity', 'gravity', single_state=True),
            #StateDependency('density_effects', 'density_effect', blocking=True),
            #StateDependency('velocity_effects', 'velocity_effect', blocking=True)
        ])
        self.pressure_solver = pressure_solver  # TODO: Adjust
        self.conserve_density = conserve_density  # TODO: Adjust

    def step(self, plasma, dt=0.1):
        """
        Computes the next state of a physical system, given the current state.
        Solves the simulation for a time increment self.dt.

        :param plasma: Initial state of the plasma for the Hasegawa-Wakatani Model
        :type plasma: PlasmaHW
        :param dt: time increment, float (can be positive, negative or zero)
        :type dt: float
        :returns: dict from String to List<State>
        :rtype: PlasmaHW
        """
        # pylint: disable-msg = arguments-differ
        domain3d = plasma.domain
        p3d = plasma.phi
        o3d = plasma.omega
        n3d = plasma.density
        shape3d = o3d.data.shape

        # Cast to 2D: Move Z-axis to Batch-axis (order: z, y, x)
        domain2d = Domain(domain3d.resolution[1:], box=domain3d.box.without_axis(0))
        o2d = o3d.copied_with(data=math.reshape(o3d.data, [-1] + list(o3d.data.shape[2:])), box=domain2d.box)
        n2d = n3d.copied_with(data=math.reshape(n3d.data, [-1] + list(n3d.data.shape[2:])), box=domain2d.box)

        # Step 1: New Phy (Poisson equation). phi_0 = ∇^-2_bot Omega_0
        # mask = plasma.domain.centered_grid(1, extrapolation='replicate')  # Tell solver: no obstacles, etc.
        # Calculate Phi from Omega
        p2d, _ = solve_pressure(o2d, FluidDomain(domain2d))
        p3d = p2d.copied_with(data=math.reshape(p2d.data, shape3d), box=domain3d.box)

        # Calculate Poisson Bracket components. Gradient on all axes (x, y)
        dy_o, dx_o = o2d.gradient(difference='central', padding='wrap').unstack()
        dy_p, dx_p = p2d.gradient(difference='central', padding='wrap').unstack()
        dy_n, dx_n = n2d.gradient(difference='central', padding='wrap').unstack()
        # Second Order for Diffusion
        #dzdz_p = p3d.laplace(axes=[0]).data[..., 0]
        nabla2_o = o3d.laplace(axes=[1, 2]).data[0, ..., 0]
        nabla2_n = n3d.laplace(axes=[1, 2]).data[0, ..., 0]
        #dzdz_o, dydy_o, dxdx_o = o3d.laplace().unstack()
        #dzdz_n, dydy_n, dxdx_n = n3d.laplace().unstack()

        # Calculate Z grad. Laplace Operator (Gradient) on 1 Dimension
        dzdz = (n3d - p3d).laplace(axes=[0]).data[..., 0]

        print(f"dzdz.shape: {dzdz.shape}")

        # Compute in numpy arrays through .data
        # Step 2.1: New Omega.
        # $\partial_t \Omega = \frac{1}{\nu} (\partial_{z}^2 n - \partial^2_{z}\phi)
        #                      - \partial_x\phi\partial_y\Omega + \partial_y\phi_0\partial_x\Omega$
        o = 1 / plasma.nu * dzdz \
            - dx_p.data * dy_o.data + dy_p.data * dx_o.data \
            + nabla2_o#dxdx_o + dydy_o  # Diffusion components
        print("delta omega = 1/{} * {} - {} + {} + {}".format(
            plasma.nu,
            np.max(dzdz),
            np.max(dx_p.data * dy_o.data),
            np.max(dy_p.data * dx_o.data),
            np.max(nabla2_o)
        ))

        # Step 2.2: New Density.
        # $\partial_t n = \frac{1}{\nu} (\partial^2_{z} n - \partial^2_{z}\phi)
        #                 - \partial_x\phi\partial_y n     + \partial_y\phi\partial_x n
        #                 - \frac{1}{n} \partial_x n \partial_y\phi$
        kappa = dx_n.data * (1 / np.sum(n2d.data))
        n = 1 / plasma.nu * dzdz \
            - dx_p.data * dy_n.data + dy_p.data * dx_n.data \
            - kappa * dy_p.data \
            + nabla2_n#dxdx_n + dydy_n  # Diffusion components
        print("delta density = 1/{} * {} - {} + {} - {} + {}".format(
            plasma.nu,
            np.max(dzdz),
            np.max(dx_p.data * dy_n.data),
            np.max(dy_p.data * dx_n.data),
            np.max(kappa * dy_p.data),
            np.max(nabla2_n)
        ))

        # Recast to 3D: return Z from Batch-axis
        p3d = euler(p3d, p3d.copied_with(data=math.reshape(p2d.data, shape3d), box=domain3d.box), dt)
        o3d = euler(o3d, o3d.copied_with(data=math.reshape(o, shape3d), box=domain3d.box), dt)
        n3d = euler(n3d, n3d.copied_with(data=math.reshape(n, shape3d), box=domain3d.box), dt)

        # phi3d     = advect.semi_lagrangian(
        #     phi3d, phi2d.copied_with(data=math.reshape(phi2d.data, shape3d), box=domain3d.box), dt=dt)
        # omega3d   = advect.semi_lagrangian(
        #     omega3d, omega3d.copied_with(data=math.reshape(omega, shape3d), box=domain3d.box), dt=dt)
        # density3d = advect.semi_lagrangian(
        #     density3d, density3d.copied_with(data=math.reshape(density, shape3d), box=domain3d.box), dt=dt)
        # density3d = density3d.normalized(density3d)
        #print("density = {}".format(density))

        return plasma.copied_with(density=n3d, omega=o3d, phi=p3d, age=(plasma.age + dt))


HASEGAWAWAKATANI = HasegawaWakatani()


def solve_pressure(omega2d, fluiddomain, pressure_solver=None):
    """
    Computes the pressure from the given Omega field with z in batch-axis using the specified solver.
    :param omega2d: CenteredGrid
    :param fluiddomain: FluidDomain instance
    :type fluiddomain: FluidDomain
    :param pressure_solver: PressureSolver to use, None for default
    :return: scalar tensor or CenteredGrid, depending on the type of divergence
    """
    assert isinstance(omega2d, CenteredGrid)
    if pressure_solver is None:
        pressure_solver = SparseCG()
    phi2d, iteration = pressure_solver.solve(omega2d.data, fluiddomain, pressure_guess=None)
    if isinstance(omega2d, CenteredGrid):
        phi2d = CenteredGrid(phi2d, omega2d.box, name='phi')
    return phi2d, iteration


def euler(x, dx, dt):
    return x + dx * dt


def get_sigma(Te0, me, ve):
    """
    $\bar{sigma} = T_{e0}/(m_e \nu_e)$
    """
    return Te0 / (me * ve)


def get_mu(me, mi, Ti, Te, sigma):
    """
    $\mu = (m_e/m_i)^{1/2} (T_i/T_e)^{5/2} \bar{\sigma}
    """
    return np.sqrt(me / mi) * np.sqrt((Ti / Te)**(5)) * sigma