use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Default)]
pub(crate) struct AppLifecycle {
    quitting: AtomicBool,
}

impl AppLifecycle {
    pub(crate) fn begin_quit(&self) {
        self.quitting.store(true, Ordering::SeqCst);
    }

    pub(crate) fn is_quitting(&self) -> bool {
        self.quitting.load(Ordering::SeqCst)
    }
}
