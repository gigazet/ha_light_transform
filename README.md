<p align="center">
  <img src="custom_components/light_transform/brand/logo.png" alt="Light Transform: RGB channels become the right light" width="768">
</p>

# Light Transform

English | [Українською](README.uk.md)

Expose what is **connected to a controller**, not what the controller advertises.

A Home Assistant custom integration that maps a physical light's channels to
ordinary CCT or brightness-only light entities. Inspired by Light Masks' virtual
light approach, but responsible for **capability and channel conversion**, not
automation priorities.

**Version:** 0.1.0. **Minimum Home Assistant:** 2026.9.3.
**Configuration:** native UI flows and output subentries. No YAML or custom actions.

## Supported mappings

| Source transport | Virtual output | Configuration |
| --- | --- | --- |
| RGB, HS or XY | CCT with dimming | Warm/cold R/G/B channels, Kelvin endpoints, mixing rule |
| RGB, HS or XY | One dimmer | One or more R/G/B channels, driven equally |
| RGB, HS or XY | Up to three independent dimmers | One output subentry per channel |
| RGB, HS or XY | CCT plus one independent dimmer | Two channels for CCT; remaining channel for dimmer |
| Native CCT | One dimmer | Fixed source color temperature |

Channels cannot overlap. One integration entry exclusively owns one physical
source. Native CCT transport uses the source's brightness and color-temperature
interface; it does **not** expose independent electrical warm/cold outputs.
RGBW/RGBWW-only sources are not supported in this version.

## Install and configure

1. Copy the `light_transform` directory inside this project's `custom_components`
   into the Home Assistant configuration's `custom_components` directory.
2. Restart Home Assistant, then open **Settings > Devices & services > Add
   integration > Light Transform**.
3. Name the controller, choose its physical `light.*`, and select **RGB channels**
   (`rgb`) or **Color temperature** (`cct`) transport. Use `rgb` for RGB/HS/XY channel mapping, even if the source also
   advertises color temperature.
4. On the integration page, choose **Add transformed output**. Each output is a
   native config subentry with its own device and stable light entity.
5. Choose **Dimmer** (`dimmer`) or **Tunable white** (`cct`). Dimmer uses only **Dimmer channels**; CCT uses only
   **Warm channel**, **Cold channel**, the Kelvin endpoints and mixing rule.
   With `cct` transport, only the name and fixed source temperature are needed.
6. Use the generated entity in dashboards, automations, scenes and light groups.
   Edit or delete individual outputs using their subentry menu.

The first setup creates a controller **without outputs**. It does not change the
physical light. Adding, editing, deleting, reloading and restarting also send no
hardware commands. Switch the source off before changing wiring or channel
assignments. Deleting an output does not turn its connected strip off; the next
command to a remaining output clears unassigned RGB channels.

### Install through HACS

In HACS, open **Custom repositories**, add
`https://github.com/gigazet/ha_light_transform` with type **Integration**, then
download **Light Transform** and restart Home Assistant. Continue from step 2
above. This is a custom repository, not a listing in the default HACS catalog.

Source and documentation: [gigazet/ha_light_transform](https://github.com/gigazet/ha_light_transform).
Report problems using the [issue tracker](https://github.com/gigazet/ha_light_transform/issues).

## Generic configuration examples

All names, entity IDs and temperatures below are illustrative, not installation
data. Configure these mappings in the UI; they are **alternatives**, except where
multiple outputs explicitly share one controller. Entity IDs depend on the names
you choose and on existing entries in your entity registry.

| Scenario | Source and transport | Output settings | Exposed controls |
| --- | --- | --- | --- |
| RGB controller + CCT strip | `light.rgb_controller`, `rgb` | CCT; warm **red**, cold **green**; 2700-6500 K; `constant_sum` | On/Off, brightness, temperature |
| RGB controller + single-color strip | `light.rgb_controller`, `rgb` | Dimmer; **red** | On/Off, brightness |
| CCT controller + fixed-white load | `light.cct_controller`, `cct` | Dimmer; fixed **3000 K**, inside the source's supported range | On/Off, brightness; 3000 K sent on every On |
| RGB controller + three single-color strips | One `light.rgb_controller`, `rgb` | Three output subentries: **red**, **green**, **blue**, one channel each | Three independent dimmers |
| RGB controller + CCT and single-color strips | One `light.rgb_controller`, `rgb` | CCT on **red + green**, dimmer on **blue** | Independent CCT light and dimmer |
| RGB controller + synchronized single-color loads | `light.rgb_controller`, `rgb` | One dimmer selecting **red + green** | One slider drives both channels equally |

Use the channel assignments and temperatures that match the **actual wiring and
strip specifications**. Channel names describe controller terminals, not the
light emitted by the connected load. Only connect electrically compatible loads
within the controller, wiring and power-supply ratings.

Do not use the source's advertised CCT range as evidence of the connected strip's
range. A controller's advertised capabilities describe its firmware, not its load.

### RGB to tunable white

```mermaid
flowchart LR
    UI["CCT light<br/>Brightness + 2700-6500 K"] --> T["Light Transform<br/>Warm/cold mixing"]
    T --> RGB["Physical RGB controller"]
    RGB --> R["R terminal: warm white"]
    RGB --> G["G terminal: cold white"]
    RGB --> B["B terminal: unused, zeroed"]
    R --> Strip["CCT strip"]
    G --> Strip
```

With 2700 K and 6500 K endpoints, the midpoint is **4600 K**. At 50% brightness,
`constant_sum` requests approximately 25% warm and 25% cold channel drive;
`constant_max` requests approximately 50% on each. Values are quantized to 8-bit
levels. These are drive ratios, not measured light output.

### Three independent dimmers on one controller

```mermaid
flowchart LR
    A["Dimmer A: red"] --> W["Shared serialized writer"]
    B["Dimmer B: green"] --> W
    C["Dimmer C: blue"] --> W
    W --> RGB["One physical RGB entity"]
    RGB --> R["R: single-color strip A"]
    RGB --> G["G: single-color strip B"]
    RGB --> BL["B: single-color strip C"]
```

Create one controller entry and three **Add transformed output** subentries,
not three controller entries. In **Developer tools > Actions**, call the normal
`light.turn_on` action on the generated dimmer A entity with `brightness_pct: 25`,
then dimmer B with `brightness_pct: 60`. Turning dimmer A off preserves B's 60%
level. Turning the final active output off sends physical Off.

### Channel accuracy warning

Some controllers advertise **`xy` or `hs` rather than native `rgb`**.
HA accepts `rgb_color` actions and converts them to the source's supported
representation. HS/XY conversion, firmware gamut clipping, gamma and hardware
calibration may mix channels or change their intensity. Native RGB is preferable
but still depends on the device honoring channel ratios.

An XY/HS source is explicitly marked `approximate_channel_control: true`.
Feedback is an estimate from HA-reported RGB plus global brightness, not a
measurement of the electrical outputs. Verify actual channel isolation at low
brightness before using separate loads. This integration is not a direct PWM
driver and cannot make a color-managed controller electrically exact.

## Behavior

- CCT outputs advertise only `color_temp`; dimmers advertise only `brightness`.
  Standard On/Off, Toggle, brightness percentages/steps, Kelvin, HA scenes and
  light groups work through the normal light domain.
- A single serialized writer composes all sibling outputs. Turning one off
  zeroes its channels, preserving the others; physical Off is sent only when
  all assigned outputs are off. Unassigned channels are zeroed on every write.
- Plain On remembers the last nonzero brightness and, for CCT outputs, temperature.
  These values persist across restarts; **On state is never restored from storage**.
  Startup adopts the current physical source without writing to it.
- Source changes update the virtual lights. Missing, unknown or unavailable
  sources make outputs unavailable. An On source in an incompatible color mode
  also makes them unavailable; turn the source off or restore its selected mode
  to recover. Sources returning from an outage are observed, not forced on.
- Registered source renames are followed using registry identity. Removing that
  identity does not silently bind to a replacement using the same entity ID.
- Service failures propagate to HA. Successful service calls are pending until
  feedback matches. `delivery_status` distinguishes `pending`, `in_sync`,
  `feedback_mismatch`, `command_failed` and unavailable/incompatible feedback.
  While pending, entities display the requested state so rapid sibling writes
  compose correctly. Pending is **not** proof of physical delivery.
- Feedback waits up to five seconds plus the requested transition. Intermediate
  or external changes during that window do not overwrite pending sibling intent.
  A mismatch logs a warning and adopts the actual reported state. It does not
  retry or fight external writers.
- Native transitions are passed through only when advertised by the source.
  They act on the **whole source's** color/brightness state; the final sibling
  levels are preserved, but independent per-channel fade trajectories cannot be
  guaranteed. Effects, flash and color loops are deliberately not exposed
  because they could activate unrelated channels.
- Download diagnostics from the integration page for mappings, current levels
  and delivery state.

### Command and feedback flow

```mermaid
sequenceDiagram
    participant User as Dashboard / automation
    participant Output as Transformed light
    participant Writer as Shared controller
    participant Source as Physical light entity
    User->>Output: Normal light action
    Output->>Writer: Update this output's intent
    Writer->>Writer: Preserve siblings, compose all channels
    Writer->>Source: One normal light action
    Note over Output,Writer: Pending until matching feedback
    Source-->>Writer: State update
    Writer-->>Output: Confirm or reconcile reported levels
    Note over Writer,Source: Timeout adopts reported state, no retry
```

### CCT mixing

Interpolation is linear in **Kelvin**, between the configured warm and cold strip
endpoints. This is an electrical drive model, not photometric calibration.

`constant_sum` (default) shares the requested drive between warm and cold.
At the midpoint, each gets half. This limits their combined drive.

`constant_max` makes the stronger channel equal the requested drive; at the
midpoint **both** get full drive. Use it only when the controller, strips and
power supply are rated for that simultaneous load.

Global source brightness is the largest composed channel level; RGB encodes
the normalized ratios. This avoids applying the brightness factor twice and
allows sibling outputs to have different absolute levels. Very low levels are
limited by 8-bit brightness/RGB quantization.

## Combining with Light Masks

```mermaid
flowchart TD
    Groups["Dashboards / automations / light groups"] --> Facade["Normal-control facade"]
    Facade --> Masks["Light Masks<br/>Optional resolver per transformed output"]
    Masks --> Transform["Light Transform<br/>Actual strip capabilities"]
    Transform --> Controller["Physical controller"]
```

Arrows indicate the direction of commands. A CCT strip should receive CCT masks,
not RGB notification effects merely because its controller advertises RGB.
For separate channels, each transformed output may have its own mask resolver.

Do not point Transform at a mask, group or another Transform entity; known
instances of these are rejected. Put Transform **below** Masks so the resolver
sees the strip's real capabilities. Custom wrappers that hide their membership
cannot all be identified automatically; select the physical controller.

Avoid parallel ownership:
existing templates, automations, Zigbee groups/bindings or direct MQTT writes to
the physical source can bypass both layers. Transform does not intercept them.

For migration, first audit consumers of any existing template lights, create the
equivalent outputs, verify the actual wiring and deliberately retarget those
consumers. Do not delete templates, rename production entities or bulk-switch
lights as part of installation. Removing this integration and leaving/restoring
the original template targets is the configuration rollback.

## Languages and artwork

English and Ukrainian are included for setup, output editing, errors and dropdown
choices. Set your Home Assistant profile language to Ukrainian to use that UI.
Internal configuration values and entity IDs are not translated.

Original brand artwork represents RGB channels passing through a transform into
warm/cool white light. Standard and high-resolution PNG icons and logos are in
`custom_components/light_transform/brand`. The artwork is covered by this
project's MIT license and uses no external images or downloaded fonts.

## Development

Python 3.14.2+ and Home Assistant 2026.9.3 are the development baseline:

```text
uv sync --group dev
uv run python -m pytest -q --timeout=30
uv run ruff check custom_components tests scripts
uv run ruff format --check custom_components tests scripts
uv run mypy
uv run python scripts/generate_brand.py
uv run python scripts/package_integration.py
```

Tests use real HA Core services/config flows with an in-memory physical light;
they do not access household devices. The full upstream pytest plugin is disabled
because its process runner is Unix-only; the public HA test context is used
directly, including on Windows.

The package script produces `dist\light_transform.zip` containing the integration
directory, including translations and brand assets, suitable for extraction into
HA's `custom_components` directory. Development caches and bytecode are excluded.
