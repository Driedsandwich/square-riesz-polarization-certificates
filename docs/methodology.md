# Methodology

## Problem

For a fixed set of source points \(X=\{x_1,\ldots,x_n\}\subset[0,1]^2\), the intensity at \(p\in[0,1]^2\) is

\[
F_X(p)=\sum_{i=1}^n \frac{1}{\|p-x_i\|^2}.
\]

The optimization objective is to place the sources so that the minimum of \(F_X\) over the square is as large as possible. This repository does not prove the global optimum over all source placements. It certifies lower bounds for the supplied fixed configurations.

## Candidate generation

Candidate configurations were found through numerical exploration, structural families, local optimization, and adversarial comparison. Candidate generation and exact certificate construction used GPT-5.6 Sol Pro under human supervision.

The release reproduces and verifies the certificates, not the original exploratory search process. Optimization/search code, random seeds, and complete search transcripts are not included in v1.0.0.

## Freezing the configuration

A selected numerical candidate is converted to an explicit finite-decimal coordinate list. The certificate treats those decimals as exact rational numbers. The claimed lower bound therefore refers to the exact published coordinates, not to an unrecorded floating-point state.

## Exact certification

The square is covered by an exact rational branch-and-bound procedure. For each box, the verifier derives a rigorous lower bound for the intensity. Boxes whose lower bound already exceeds the target are discarded; remaining boxes are subdivided until the entire square is certified.

Two verifier methods are included:

1. a spectral Hessian lower bound;
2. componentwise rational bounds for \(H_{xx}\), \(H_{yy}\), and \(H_{xy}\).

They use different rigorous second-order remainder bounds, but share the coordinates, rational arithmetic, and branch-and-bound architecture. They are complementary checks, not fully independent proof systems.

## Numerical analysis versus proof

Numerical local-minimum enumeration and rendering information help diagnose and display a configuration. The result tables include local-minimum counts where available. Full local-minimum coordinate lists are not included in v1.0.0, and none of this numerical material is required by the exact lower-bound proof.

## Reproduction

See `docs/reproducibility.md` for commands that verify one certificate, the manifest, or all 88 certifier scripts.
