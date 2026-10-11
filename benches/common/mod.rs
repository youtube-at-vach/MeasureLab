// Cargo bench passes --bench even to harness-free targets; cargo test does not.
// Exercise each case once by default and repeat only for explicit benchmarks.
pub fn iterations(measured: usize) -> usize {
    if std::env::args().any(|arg| arg == "--bench") {
        measured
    } else {
        1
    }
}
