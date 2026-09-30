//! Exact checked rational time arithmetic. Nominal rates never establish clock synchronization.
use crate::{Rational, Timebase};
use serde::{Deserialize, Serialize};

fn gcd(mut a: u128, mut b: u128) -> u128 {
    while b != 0 {
        (a, b) = (b, a % b);
    }
    a
}
fn ratio(n: i128, d: u128) -> Result<Rational, String> {
    if d == 0 {
        return Err("invalid_rational".into());
    }
    let common = gcd(n.unsigned_abs(), d);
    let magnitude = i128::try_from(n.unsigned_abs() / common).map_err(|_| "rational_overflow")?;
    let reduced = if n < 0 { -magnitude } else { magnitude };
    Ok(Rational {
        numerator: i64::try_from(reduced).map_err(|_| "rational_overflow")?,
        denominator: u64::try_from(d / common).map_err(|_| "rational_overflow")?,
    })
}
impl Rational {
    pub fn normalized(&self) -> Result<Self, String> {
        ratio(i128::from(self.numerator), u128::from(self.denominator))
    }
    fn add(&self, other: &Self) -> Result<Self, String> {
        self.normalized()?;
        other.normalized()?;
        let n = i128::from(self.numerator)
            .checked_mul(i128::from(other.denominator))
            .and_then(|left| {
                i128::from(other.numerator)
                    .checked_mul(i128::from(self.denominator))
                    .and_then(|right| left.checked_add(right))
            })
            .ok_or("rational_overflow")?;
        ratio(
            n,
            u128::from(self.denominator) * u128::from(other.denominator),
        )
    }
    fn scaled(&self, count: i128) -> Result<Self, String> {
        ratio(
            i128::from(self.numerator)
                .checked_mul(count)
                .ok_or("rational_overflow")?,
            u128::from(self.denominator),
        )
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ClockMapping {
    pub from: (String, u64),
    pub to: (String, u64),
    pub offset: Rational,
    pub ratio: Rational,
    pub valid_interval: [i64; 2],
    pub method: String,
    pub uncertainty_samples: Option<Rational>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct TimeRelation {
    pub value: Option<Rational>,
    pub reason: Option<String>,
    pub mapping: Option<ClockMapping>,
    pub uncertainty_seconds: Option<Rational>,
}
pub fn relation(
    left: &Timebase,
    right: &Timebase,
    mapping: Option<&ClockMapping>,
    sample: i64,
) -> Result<TimeRelation, String> {
    if !left.valid() || !right.valid() {
        return Err("invalid_timebase".into());
    }
    let mut result = TimeRelation {
        value: None,
        reason: None,
        mapping: None,
        uncertainty_seconds: None,
    };
    if let Some(m) = mapping {
        if m.from != (left.id.clone(), left.generation)
            || m.to != (right.id.clone(), right.generation)
            || !(m.valid_interval[0]..m.valid_interval[1]).contains(&sample)
        {
            result.reason = Some("unsynchronized".into());
            return Ok(result);
        }
        if m.method.is_empty()
            || !m.ratio.valid()
            || m.ratio.numerator <= 0
            || !m.offset.valid()
            || m.uncertainty_samples
                .as_ref()
                .is_some_and(|r| !r.valid() || r.numerator < 0)
        {
            return Err("invalid_mapping".into());
        }
        result.value = Some(m.offset.add(&m.ratio.scaled(i128::from(sample))?)?);
        result.mapping = Some(m.clone());
    } else if left.clock_domain != right.clock_domain {
        result.reason = Some("unsynchronized".into());
    } else if let Some(origin) = &left.origin_seconds {
        let elapsed = ratio(
            (i128::from(sample) - i128::from(left.origin_sample))
                .checked_mul(i128::from(left.rate.denominator))
                .ok_or("rational_overflow")?,
            left.rate.numerator as u128,
        )?;
        result.value = Some(origin.add(&elapsed)?);
        result.uncertainty_seconds = left.uncertainty_seconds.clone();
    } else {
        result.reason = Some("unknown_origin".into());
    }
    Ok(result)
}
