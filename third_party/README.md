# Container dependency notices

The reproducibility image contains the following separately licensed routing
components. These notices do not change the licence of CIW source code.

| Component | Version | Selected licence | Upstream |
| --- | --- | --- | --- |
| r5py | 1.1.7 | MIT option of `GPL-3.0-or-later OR MIT` | <https://github.com/r5py/r5py/tree/v1.1.7> |
| R5 routing engine | 7.5.1-r5py | MIT | <https://github.com/r5py/r5/releases/tag/v7.5.1-r5py> |

The embedded R5 JAR is
`r5-v7.5.1-r5py-all.jar`, SHA-256
`d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7`.
It also contains its dependencies' own `META-INF` licence and notice files;
those files must remain inside any redistributed JAR. The licence texts in
this directory are unmodified copies from the pinned upstream tags.
