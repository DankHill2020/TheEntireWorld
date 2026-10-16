# Joint-placement regression corpus

This directory holds versioned golden baselines and the suite manifest. Studio
production scenes remain in the asset depot. Small redistributable test assets
may live under `assets/` when their license and provenance are checked in beside
them.

The default corpus combines two kinds of evidence:

- Studio-approved rigs use `build_skeleton: false` and compare the placement
  preview with their existing canonical skeleton anchors.
- Redistributable source rigs use `build_skeleton: true`; their approved joints
  are mapped to studio joint names and compared with a newly fitted 280-joint
  template.

The checked-in default set contains Juice and John Healthy from the studio
depot, plus the female and male full-body characters from Quaternius Universal
Base Characters (CC0 1.0). A manifest case has this form:

```json
{
  "id": "adult_human_t_pose_01",
  "scene": "C:/depot/ArtSource/RigTests/adult_human_t_pose_01.ma",
  "mesh": "body_geo",
  "baseline": "baselines/adult_human_t_pose_01.json",
  "build_skeleton": true
}
```

Build the initial corpus around meaningful shape classes: male/female body
proportions, short/tall and heavy/thin bodies, T- and A-poses, scans with noisy
topology, separated clothing shells, stylized characters, and characters with
unusual hand proportions. Every baseline must be visually approved before it
is committed.

The normalized hard gates cover core-anchor error, bone-length ratios, volume
containment, anatomical ordering, chain-plane deviation, HumanIK-compatible
template counts, and reverse-foot helpers. A failing case is a placement
regression, not an instruction to loosen thresholds without reviewing the rig.
