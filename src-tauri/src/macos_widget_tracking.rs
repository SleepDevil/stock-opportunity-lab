use std::ffi::c_void;

use objc2::ffi::{
    OBJC_ASSOCIATION_RETAIN_NONATOMIC, objc_getAssociatedObject, objc_setAssociatedObject,
};
use objc2::rc::Retained;
use objc2::runtime::AnyObject;
use objc2::{AnyThread, DefinedClass, MainThreadOnly, define_class, msg_send};
use objc2_app_kit::{NSEvent, NSTrackingArea, NSTrackingAreaOptions, NSView};
use objc2_foundation::{MainThreadMarker, NSObject, NSObjectProtocol, NSPoint, NSRect, NSSize};
use tauri::Manager;

use crate::widget::{pointer_entered, pointer_exited};

static WIDGET_TRACKING_OWNER_KEY: u8 = 0;

struct WidgetTrackingOwnerIvars {
    app: tauri::AppHandle,
}

define_class!(
    // SAFETY: NSObject has no additional subclassing requirements. AppKit
    // delivers tracking-area callbacks on the main thread.
    #[unsafe(super = NSObject)]
    #[thread_kind = MainThreadOnly]
    #[ivars = WidgetTrackingOwnerIvars]
    struct WidgetTrackingOwner;

    // SAFETY: NSObjectProtocol has no additional implementation requirements.
    unsafe impl NSObjectProtocol for WidgetTrackingOwner {}

    impl WidgetTrackingOwner {
        #[unsafe(method(mouseEntered:))]
        fn mouse_entered(&self, _event: &NSEvent) {
            pointer_entered(&self.ivars().app);
        }

        #[unsafe(method(mouseExited:))]
        fn mouse_exited(&self, _event: &NSEvent) {
            pointer_exited(&self.ivars().app);
        }
    }
);

impl WidgetTrackingOwner {
    fn new(mtm: MainThreadMarker, app: tauri::AppHandle) -> Retained<Self> {
        let this = Self::alloc(mtm).set_ivars(WidgetTrackingOwnerIvars { app });
        // SAFETY: The signature of NSObject's init method is correct.
        unsafe { msg_send![super(this), init] }
    }
}

pub(crate) fn install(app: &tauri::AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("widget")
        .ok_or_else(|| "widget window is not available".to_string())?;
    if MainThreadMarker::new().is_some() {
        return install_on_main_thread(&window, app.clone());
    }

    let app = app.clone();
    let window_for_main_thread = window.clone();
    window
        .run_on_main_thread(move || {
            if let Err(error) = install_on_main_thread(&window_for_main_thread, app.clone()) {
                log::error!("failed to install native widget tracking area: {error}");
                crate::widget::start_hover_polling(app);
            }
        })
        .map_err(|error| error.to_string())
}

fn install_on_main_thread(
    window: &tauri::WebviewWindow,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let mtm = MainThreadMarker::new()
        .ok_or_else(|| "native widget tracking must be installed on the main thread".to_string())?;
    let view_pointer = window.ns_view().map_err(|error| error.to_string())?;
    if view_pointer.is_null() {
        return Err("widget NSView is not available".to_string());
    }

    // SAFETY: Tauri returns the content NSView for this window and the closure
    // is running on the AppKit main thread. The view owns its tracking areas.
    unsafe {
        let view = &*view_pointer.cast::<NSView>();
        let view_object = view_pointer.cast::<AnyObject>();
        let association_key = std::ptr::addr_of!(WIDGET_TRACKING_OWNER_KEY).cast::<c_void>();
        if !objc_getAssociatedObject(view_object, association_key).is_null() {
            return Ok(());
        }

        let owner = WidgetTrackingOwner::new(mtm, app);
        let options = NSTrackingAreaOptions::MouseEnteredAndExited
            | NSTrackingAreaOptions::ActiveAlways
            | NSTrackingAreaOptions::InVisibleRect
            | NSTrackingAreaOptions::EnabledDuringMouseDrag;
        let area = NSTrackingArea::initWithRect_options_owner_userInfo(
            NSTrackingArea::alloc(),
            NSRect::new(NSPoint::new(0.0, 0.0), NSSize::new(0.0, 0.0)),
            options,
            Some(
                Retained::as_ptr(&owner)
                    .cast::<AnyObject>()
                    .as_ref()
                    .unwrap(),
            ),
            None,
        );
        view.addTrackingArea(&area);

        // NSTrackingArea does not own its callback target. Associate the owner
        // with the NSView so both share the window's lifetime.
        objc_setAssociatedObject(
            view_object,
            association_key,
            Retained::as_ptr(&owner).cast_mut().cast::<AnyObject>(),
            OBJC_ASSOCIATION_RETAIN_NONATOMIC,
        );
    }
    log::info!("installed native macOS widget tracking area");
    Ok(())
}
