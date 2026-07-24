# Refrigeration layout editor

The refrigeration equipment detail page uses a responsive DOM overlay for sensor placement over an equipment photo.

## Editing model

- Published equipment data remains read-only.
- Editing starts from an in-memory draft copy.
- Sensor coordinates are normalized to the inclusive range `0..1`.
- Pointer drag and keyboard movement use the same movement pipeline.
- Optional snapping supports a 40 × 40 grid or predefined sensor slots.
- Undo and redo store bounded move commands.
- Cancel restores the last saved draft state.
- Replacing the photo preserves all sensor placements.

## Photo validation

Accepted formats are JPEG, PNG, and WebP. The current client-side limit is 15 MB. Production object storage and versioned publishing are handled in a later implementation scope.
