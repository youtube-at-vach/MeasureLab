## 2024-05-28 - Optimize Arbitrary Harmonic Generator math with matrix multiplication

**Learning:** When calculating many harmonic sine waves with arbitrary amplitudes and phases, broadcasting a full (harmonics, frames) array and computing `np.sin()` on it is slow and memory intensive. The fastest way is to mathematically decompose the amplitude and phase into real and imaginary coefficients using the sine addition formula, and then compute the final signal in one go using matrix multiplication (`@`) against a pre-computed array of pure harmonic sine/cosine basis vectors.

**Action:** When vectorizing audio harmonic generation, use dot products (`@`) instead of looping over harmonics or broadcasting large arrays inside `np.sin()`.
