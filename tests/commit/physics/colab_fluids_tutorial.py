from unittest import TestCase

from phi.flow import *
from phi.tf import TF_BACKEND


class ColabNotebookTest(TestCase):

    def test_gradient(self):
        with TF_BACKEND:
            DOMAIN = Domain(x=32, y=40, boundaries=CLOSED, bounds=Box[0:32, 0:40])
            INFLOW_LOCATION = math.tensor([(4., 5), (8., 5), (12., 5), (16., 5)], 'inflow_loc,vector', convert=True)
            INFLOW = DOMAIN.grid(Sphere(center=INFLOW_LOCATION, radius=3)) * 0.6

            smoke = DOMAIN.scalar_grid(math.zeros(inflow_loc=4))
            velocity = initial_velocity = DOMAIN.staggered_grid(0) * math.ones(inflow_loc=4)

            with math.record_gradients(velocity.values):
                for _ in range(4):
                    smoke = advect.mac_cormack(smoke, velocity, dt=1) + INFLOW
                    buoyancy_force = smoke * (0, 0.5) >> velocity
                    velocity = advect.semi_lagrangian(velocity, velocity, dt=1) + buoyancy_force
                    velocity, _, _, _ = fluid.make_incompressible(velocity, DOMAIN)
                loss = field.l2_loss(smoke - field.stop_gradient(smoke.inflow_loc[-1]))
                grad = math.gradients(loss, initial_velocity.values)
