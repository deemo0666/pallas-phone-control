//! One readable line (or a few) from an error and its causes. Written for Pallas (MIT).

use std::error::Error;

use rootcause::Report;

/// Each line of a report's tree, without the drawing characters, repeats dropped.
pub(crate) fn report_text(report: &Report) -> String {
    let mut lines: Vec<String> = Vec::new();
    for line in format!("{report}").lines() {
        let text = line
            .trim_start_matches(|c: char| c.is_whitespace() || "│├└─╰┬●|-*".contains(c))
            .trim();
        if text.is_empty() || text.starts_with("at ") || lines.iter().any(|l| l == text) {
            continue;
        }
        lines.push(text.to_string());
    }
    if lines.is_empty() { "unknown error".into() } else { lines.join("\n") }
}

/// The error, then each cause that adds something, joined by ": ".
pub(crate) fn error_text(error: &(dyn Error + 'static)) -> String {
    let mut out = error.to_string();
    let mut next = error.source();
    while let Some(cause) = next {
        let text = cause.to_string();
        if !text.is_empty() && !out.contains(&text) {
            out.push_str(": ");
            out.push_str(&text);
        }
        next = cause.source();
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug)]
    struct E(&'static str, Option<Box<E>>);
    impl std::fmt::Display for E {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { f.write_str(self.0) }
    }
    impl Error for E {
        fn source(&self) -> Option<&(dyn Error + 'static)> { self.1.as_deref().map(|e| e as _) }
    }

    #[test]
    fn causes_are_joined_without_repeats() {
        let e = E("install failed", Some(Box::new(E("timed out", Some(Box::new(E("timed out", None)))))));
        assert_eq!(error_text(&e), "install failed: timed out");
    }
}
