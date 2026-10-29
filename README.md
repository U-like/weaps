# DirectP2P LAB — NAT diagnostics snapshot

This branch isolates the standalone Android/Python DirectP2P experiment and the observed cross-network NAT test results from the production messenger.

- [NAT diagnostic findings and next-step plan](NAT_TEST_MATRIX.md)
- The existing `directp2p-project.tar.xz` and GitHub Actions workflow are the **older baseline**; do not label them v0.2.
- DirectP2P LAB 0.2 diagnostic source files, its APK, and the full Git history snapshot are preserved separately as a portable Git bundle (local commit `677f6d34f78d0c6ef8c737a40e87f21fd9397d79`). The bundle can be fetched into a local repository and pushed to an independent branch. The source bundle is not yet uploaded to GitHub by this commit.
- Main Android messenger: `U-like/p2p_messenger` — untouched.

The test matrix uses anonymized network labels because this GitHub repository is public.
