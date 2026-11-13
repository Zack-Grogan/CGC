# Standards validation

CGC uses the official Khronos glTF Validator through a project-scoped Node package. Run setup explicitly; generation does not install software during validation.

```sh
cgc validate setup
cgc validate gltf --input ./asset.glb -o ./asset-validation.json --json
```

The tool validates the bytes that it hashes. Reports retain errors, warnings, informational messages, resource hashes, and the pinned validator version. A truncated report does not pass. Use `--warnings-as-errors` when a delivery contract requires zero warnings.

For text glTF assets, external resources must be local and inside the asset directory. Supply `--resource-root ./project-assets` to allow referenced sibling folders within an explicit root. Remote resource URLs are not fetched. An unavailable resource fails validation; it is not treated as a verified dependency.

```sh
cgc validate gltf --input ./project-assets/models/ship.gltf \
  --resource-root ./project-assets --warnings-as-errors --json
```

The validator checks the glTF specification. It does not establish good art direction, useful topology, convincing deformation, correct real-world scale, an appropriate collider, or compatibility with every engine extension. Engine import and gameplay checks remain separate.

The baseline audit found two schema errors in an earlier textured split: empty `extensionsUsed` and `extensionsRequired` arrays inherited from its source. The texture conversion, splitting, and replacement exporters now omit those empty optional fields. The regenerated split passes the official validator without errors or warnings. Original files and the baseline report remain unchanged in `outputs/quality-upgrade/`.

## Sources and implementation decisions

- [Official validator Node API](https://github.com/KhronosGroup/glTF-Validator/blob/main/node/README.md): use `validateBytes` and retain its issue report rather than infer validity from a GLB header or successful import.
- [Official validator scope](https://github.com/KhronosGroup/glTF-Validator/blob/main/README.md): specification validation is one layer of acceptance.
- [Khronos material tutorial](https://github.com/KhronosGroup/glTF-Tutorials/blob/main/gltfTutorial/gltfTutorial_010_Materials.md): retain the metallic-roughness material model and declare texture roles.
- [glTF Transform CLI](https://gltf-transform.dev/cli): production optimization offers compression and texture conversion, but those transformations need target-engine support. CGC does not blindly apply the cookbook's Draco/WebP example to Bevy assets.
- [Unity glTFast](https://github.com/Unity-Technologies/com.unity.cloud.gltfast/blob/main/Packages/com.unity.cloud.gltfast/README.md): Unity's glTF workflow requires a compatible importer package; a file extension alone does not establish editor integration.
- [Unreal Interchange reference](https://dev.epicgames.com/documentation/en-us/unreal-engine/interchange-import-reference-in-unreal-engine): import settings and collision conventions remain explicit. An exported FBX derivative is not an Unreal-editor test.

The installed validator is `gltf-validator@2.0.0-dev.3.10`. The project package lock pins its integrity. This is software setup only; it downloads no generation models.
