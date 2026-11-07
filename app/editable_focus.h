#pragma once
#include <atspi/atspi.h>
#include <string>
#include <memory>
#include <unistd.h>
#include "accessible_state_probe.h"

// Listen only for focus state. Never request accessible names, values or text.
struct EditableFocus {
    AtspiEventListener* listener = nullptr;
    bool available = false, editable = false, password = false, request = false;
    unsigned events = 0;
    std::string focused_object;
    AtspiAccessible* editor = nullptr;
    AtspiAccessible* control = nullptr;
    unsigned restores = 0, failures = 0, expirations = 0;
    unsigned refresh_failures = 0;
    AtspiRole control_role = ATSPI_ROLE_INVALID;
    AccessibleStateProbe state_probe;

    static unsigned sender_pid(AtspiObject* object) {
        if (!object || !object->app || !object->app->bus_name) return 0;
        // Ask the bus daemon for the peer's HOST PID; namespace PIDs can collide.
        auto* query = dbus_message_new_method_call(DBUS_SERVICE_DBUS, DBUS_PATH_DBUS, DBUS_INTERFACE_DBUS, "GetConnectionUnixProcessID");
        const char* sender = object->app->bus_name;
        dbus_message_append_args(query, DBUS_TYPE_STRING, &sender, DBUS_TYPE_INVALID);
        auto* reply = dbus_connection_send_with_reply_and_block(atspi_get_a11y_bus(), query, 150, nullptr);
        dbus_message_unref(query);
        if (!reply) return 0;
        dbus_uint32_t pid = 0;
        const bool valid = dbus_message_get_args(reply, nullptr, DBUS_TYPE_UINT32, &pid, DBUS_TYPE_INVALID);
        dbus_message_unref(reply);
        return valid ? pid : 0;
    }
    static bool own_sender(AtspiObject* object) {
        const auto pid = sender_pid(object);
        return pid && getpgid(pid) == getpgrp();
    }

    static void focus_changed(AtspiEvent* event, void* data) {
        const auto free_event = [](AtspiEvent* value) { g_boxed_free(ATSPI_TYPE_EVENT, value); };
        std::unique_ptr<AtspiEvent, decltype(free_event)> owned_event(event, free_event);
        auto& self = *static_cast<EditableFocus*>(data);
        if (!event->source) return;
        auto* object = ATSPI_OBJECT(event->source);
        if (!own_sender(object)) return;
        ++self.events;
        const std::string identity = std::string(object->app->bus_name) + object->path;
        if (!event->detail1) {
            if (identity == self.focused_object) { self.editable = false; self.request = false; self.focused_object.clear(); }
            return;
        }
        auto* states = atspi_accessible_get_state_set(event->source);
        const auto role = atspi_accessible_get_role(event->source, nullptr);
        // detail1 is the focus transition itself; the cached FOCUSED state can
        // still describe the previous frame when this callback is delivered.
        self.editable = states && atspi_state_set_contains(states, ATSPI_STATE_EDITABLE)
            && atspi_state_set_contains(states, ATSPI_STATE_ENABLED);
        self.password = role == ATSPI_ROLE_PASSWORD_TEXT;
        // Chrome reports the document itself focused after element.blur().
        // This is not a newly selected control. Pointer clicks outside the
        // field already retire it; hidden/detached targets fail dispatch checks.
        const bool document_blur=role==ATSPI_ROLE_DOCUMENT_WEB && self.editor;
        if (!self.editable && !document_blur) {
            self.clear_editor();
            const bool container=role==ATSPI_ROLE_DOCUMENT_WEB || role==ATSPI_ROLE_FRAME ||
                role==ATSPI_ROLE_ROOT_PANE || role==ATSPI_ROLE_APPLICATION || role==ATSPI_ROLE_WINDOW;
            if (!container) { self.control=ATSPI_ACCESSIBLE(g_object_ref(event->source));self.control_role=role; }
        } else if (self.control) { g_object_unref(self.control);self.control=nullptr; }
        self.focused_object = identity;
        if (self.editable && self.editor!=event->source) {
            self.state_probe.cancel();
            if (self.editor) g_object_unref(self.editor);
            self.editor=ATSPI_ACCESSIBLE(g_object_ref(event->source));
        }
        if (states) g_object_unref(states);
        self.request = self.editable;
    }

    void start() {
        if (atspi_init() != 0) return;
        atspi_set_timeout(150, 150);
        listener = atspi_event_listener_new(focus_changed, this, nullptr);
        available = atspi_event_listener_register(listener, "object:state-changed:focused", nullptr);
    }
    void poll() { for (int i=0; i<8 && g_main_context_pending(nullptr); ++i) g_main_context_iteration(nullptr, false); }
    void clear_editor() {
        state_probe.cancel();
        if (editor) g_object_unref(editor);
        if (control) g_object_unref(control);
        editor=nullptr;control=nullptr;
        control_role=ATSPI_ROLE_INVALID;
        editable=false;password=false;request=false;focused_object.clear();
    }
    void browser_click(int x,int y) {
        // A second click inside the same field may emit no focus event. Keep
        // that target; retire it before clicks elsewhere select a new element.
        bool inside=false;
        auto* component=editor?atspi_accessible_get_component_iface(editor):nullptr;
        if (component) {
            GError* error=nullptr;
            auto* rect=atspi_component_get_extents(component,ATSPI_COORD_TYPE_SCREEN,&error);
            inside=!error && rect && x>=rect->x && y>=rect->y &&
                x<rect->x+rect->width && y<rect->y+rect->height;
            if (rect) g_boxed_free(ATSPI_TYPE_RECT,rect);
            if (error) g_error_free(error);
            g_object_unref(component);
        }
        if (!inside) clear_editor();
    }
    bool focus_editor(bool navigation=false) {
        // Retain only the user's selected element, never its contents. A browser
        // window can be focused while its text field has lost DOM focus.
        auto* target=editor?editor:control;
        if (!target || !own_sender(ATSPI_OBJECT(target))) { clear_editor();++failures;return false; }
        atspi_accessible_clear_cache_single(target);
        auto* states=atspi_accessible_get_state_set(target);
        const bool focused=states && atspi_state_set_contains(states,ATSPI_STATE_FOCUSED);
        const bool valid=states && (editor?atspi_state_set_contains(states,ATSPI_STATE_EDITABLE):navigation && focused) &&
            atspi_state_set_contains(states,ATSPI_STATE_ENABLED) && atspi_state_set_contains(states,ATSPI_STATE_VISIBLE) &&
            atspi_state_set_contains(states,ATSPI_STATE_SHOWING) && !atspi_state_set_contains(states,ATSPI_STATE_DEFUNCT);
        if (states) g_object_unref(states);
        if (!valid) { clear_editor();++failures;return false; }
        // Do not reset a live caret/selection, or pull Tab back from a button.
        if (focused) return true;
        auto* component=atspi_accessible_get_component_iface(editor);
        if (!component) { clear_editor();++failures;return false; }
        GError* error=nullptr;
        const bool restored=atspi_component_grab_focus(component,&error);
        if (error) g_error_free(error);
        g_object_unref(component);
        if (restored) ++restores;else { clear_editor();++failures; }
        return restored;
    }
    void refresh_editor(bool begin) {
        if (!editor) { state_probe.cancel();return; }
        const auto result=state_probe.poll();
        if (result==AccessibleStateProbe::Result::Invalid) { clear_editor();++expirations;return; }
        if (result==AccessibleStateProbe::Result::Unknown) ++refresh_failures;
        // A timeout is inconclusive. Key dispatch still performs its separate,
        // fail-closed validation before sending any input.
        if (begin && !state_probe.pending) {
            auto* object=ATSPI_OBJECT(editor);
            if (object->app) state_probe.start(object->app->bus,object->app->bus_name,object->path);
        }
    }
    ~EditableFocus() {
        clear_editor();
        if (listener) {
            atspi_event_listener_deregister(listener, "object:state-changed:focused", nullptr);
            g_object_unref(listener);
        }
    }
};
