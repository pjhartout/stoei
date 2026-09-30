mod unix;

pub(super) use unix::{Stdin, Waiter};

pub(super) type Wake = Box<dyn Fn() + Send + Sync>;
