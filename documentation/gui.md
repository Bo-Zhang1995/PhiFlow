
# Φ-*Flow* Browser GUI

Φ-*Flow* contains an interactive GUI that can display any kind of two-dimensional or three-dimensional fields. The interface is displayed in the browser and is very easy to set up.

The default GUI will display your application in the browser.
If you intend to use the GUI for interactive training of a TensorFlow model, make sure to read the TensorFlow specific sections below. Else, you can simply create a subclass of [FieldSequenceModel](../phi/model.py) as described below.

## General (Non-TensorFlow) App

### Simple Example

The following code defines a custom [FieldSequenceModel](../phi/model.py) and uses it to launch the GUI.

```python
from phi.model import *

class GuiTest(FieldSequenceModel):
    def __init__(self):
        FieldSequenceModel.__init__(self, "Test", "Hello World!")

app = GuiTest().show(production=__name__!="__main__")
```

When run, the application prints a URL to the console. Enter this URL into a browser to view the GUI. See Known Issues for restrictions.

You should see the _Hello World_ text at the top, followed by two empty diagrams and a bunch of controls. None of the controls will do anythong useful at this point so let's focus on the diagrams.

A key part of any [FieldSequenceModel](../phi/model.py) is that it contains two or three-dimensional fields which can change over time. How these fields are generated and how they evolve is up to the application. They could change as part of an evolving fluid simulation, they could be the predictions of a neural network that is being optimized or they could simply be a sequence read from disc.

In any case, these fields must be exposed to the GUI. This is done by calling the inherited `add_field` method in the constructor. Its first argument is the name (can contain unicode characters) and the second is a field generator, typically a lambda expression.

A simple example, generating random fields could look like this

```python
class GuiTest(FieldSequenceModel):
    def __init__(self):
        FieldSequenceModel.__init__(self, "Random", "Generates random fields")
        self.add_field("Random Scalar", lambda: np.random.rand(1, 16, 16, 1))
        self.add_field("Random Vector", lambda: np.random.rand(1, 16, 16, 3))
```

On startup, the GUI will automatically display the two fields.

### The `step` Method

The `step` method is the core part of the model. It defines how the next step is calculated. This could mean running one simulation step, loading data from disc or running a training pass for a neural network.

Your subclass of [FieldSequenceModel](../phi/model.py) automatically inherits the variable `time` which holds the current frame as an integer. It is automatically incremented before step is called and is displayed in the GUI, below the diagrams.

After `step` finishes, the GUI is updated to reflect the change in the data. Consequently, the field generators (lambda expressions in the above example) can be called after each step. In practice, however, steps can often be performed at a higher framerate than the GUI update rate.


### Custom Controls

To create an interactive application, it is useful to add control element which the user can use to manipulate the simulation or training process.

Currently, the following control types are supported:

- Floating point controls (sliders)
- Integer controls (sliders)
- Boolean controls (checkboxes)
- Text controls (text fields)
- Action controls (buttons)

The easiest way to add controls is to create an attribute with the prefix `value_`.

```python
    self.value_temperature = 39.5
    self.value_windows_open = False
    self.value_message = "It's too hot!"
    self.value_limit = 42
```

The type of controls is derived from the assigned value and the corresponding control element is automatically added to the GUI.

Analogously, actions are created from methods with the prefix `action_`.

```python
    def action_reset(self):
        pass
```

Controls can be configured by creating an instance of `EditableValue`. In this case, the prefix `value_` is not needed.

```python
    self.temperature = EditableFloat("Temperature", 40.2)
    self.windows_open = EditableBool("Windows Open?", False)
    self.message = EditableString("Message", "It's too hot!")
    self.limit = EditableInt("Limit", 42, (20, 50))
```


## TensorFlow App

If the purpose of your application is to train a TensorFlow model, you can extend from [TFModel](../phi/tf/model.py) instead. This has a couple of benefits:

- Model parameters can be saved and loaded from the GUI
- Summaries including the loss value are created and can easily be extended using `add_scalar`
- [TensorBoard](https://www.tensorflow.org/guide/summaries_and_tensorboard) can be launched from the GUI
- Profiling tools can be used in the browser
- A database is set up (see [the guide on data handling](data.md))
- The `step` method is implemented by default
- Tensor nodes and database field names can be passed to `add_field`
- Properties and the application source file are written to the output directory
- A learning rate control is available by default and more controls can be created easily using `editable_float`, `editable_int`

### Simple Example

The following example trains a neural network, referenced as `network` to predict a force field from two velocity fields.

```python
from phi.tf.model import *
from phi.data import *

class TrainingTest(TFModel):

    def __init__(self):
        TFModel.__init__(self, "Training")
        sim = self.sim = TFFluidSimulation([128] * 2, "open")

        initial_velocity = sim.placeholder("velocity", "InitialVelocity")
        target_velocity = sim.placeholder("velocity", "TargetVelocity")
        true_force = sim.placeholder("velocity", "Force") * self.editable_float("Scale", 1.0)

        with self.model_scope():
            pred_force = network(initial_velocity, target_velocity)
        loss = l2_loss(pred_force - true_force)
        self.minimizer("Supervised_Loss", loss)

        self.database.add(["InitialVelocity", "TargetVelocity", "Force"])
        self.database.put_scenes(scenes("SmokeIK/forces"), logf=self.info)
        self.finalize_setup([initial_velocity, target_velocity, true_force])

        self.add_field("Force (Ground Truth)", "Force")
        self.add_field("Force (Model)", pred_force)

app = TrainingTest().show(production=__name__!="__main__")
```

Let's go over what's happening here in detail.
First, the app calls the super constructor, passing only the app's name.
Next, the fluid simulation is created and assigned to `self.sim`. This variable is inherited from `TFModel` and must be initialized with a `TFFluidSimulation` in the constructor.

The following three lines create input fields for TensorFlow's graph. We allow the true_force tensor to be scaled by a user-defined value which can be set in the GUI.

Now that the network inputs are set up, the network can be built. The use of `with self.model_scope()` ensures that the network parameters can be saved and loaded automatically and from the GUI.
The `l2_loss` is part of Φ-*Flow*'s n-d math package but a regular TensorFlow loss can also be used.
The inherited method `minimizer` sets up the optimizer. This optimizer will be used in the default `step` implementation.

The following block sets up the database by registering the required fields and adding all scenes from one category (see [the data documentation](data.md) for more).
The call to `finalize_setup` is mandatory in the constructor and sets up the TensorFlow summary as well as database iterators.

Finally, the viewable fields are exposed to the GUI. The first line exposes the field `Force` which was registered with the database while the second line exposes the graph output `pred_force` which will be recalculated each time the GUI is updated.

Lastly, the app is instantiated and the GUI created in the same way as with a [FieldSequenceModel](../phi/model.py).
