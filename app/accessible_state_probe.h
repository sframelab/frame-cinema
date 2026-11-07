#pragma once
#include <atspi/atspi.h>
#include <cstring>
#include <chrono>

// Only role-independent state bits cross this query; never text or values.
// AT-SPI's synchronous state accessor conflates failed replies with DEFUNCT.
struct AccessibleStateProbe {
    enum class Result { Pending, Unknown, Valid, Invalid };
    DBusPendingCall* pending = nullptr;
    std::chrono::steady_clock::time_point deadline{};
    AccessibleStateProbe() = default;
    AccessibleStateProbe(const AccessibleStateProbe&) = delete;
    AccessibleStateProbe& operator=(const AccessibleStateProbe&) = delete;
    void cancel() {
        if (pending) { dbus_pending_call_cancel(pending);dbus_pending_call_unref(pending);pending=nullptr; }
    }
    bool start(DBusConnection* bus,const char* destination,const char* path) {
        if (pending || !bus || !destination || !path) return false;
        auto* message=dbus_message_new_method_call(destination,path,"org.a11y.atspi.Accessible","GetState");
        if (!message) return false;
        const bool sent=dbus_connection_send_with_reply(bus,message,&pending,150);
        dbus_message_unref(message);
        deadline=std::chrono::steady_clock::now()+std::chrono::milliseconds(150);
        return sent && pending;
    }
    static Result decode(DBusMessage* reply) {
        if (!reply) return Result::Unknown;
        if (dbus_message_get_type(reply)==DBUS_MESSAGE_TYPE_ERROR) {
            const auto* error=dbus_message_get_error_name(reply);
            return error && std::strcmp(error,DBUS_ERROR_UNKNOWN_OBJECT)==0 ? Result::Invalid : Result::Unknown;
        }
        dbus_uint32_t* bits=nullptr;int count=0;
        if (dbus_message_get_type(reply)!=DBUS_MESSAGE_TYPE_METHOD_RETURN ||
            !dbus_message_get_args(reply,nullptr,DBUS_TYPE_ARRAY,DBUS_TYPE_UINT32,&bits,&count,DBUS_TYPE_INVALID) || count!=2)
            return Result::Unknown;
        auto has=[&](AtspiStateType state) { return (bits[unsigned(state)/32] & (1u<<(unsigned(state)%32)))!=0; };
        return has(ATSPI_STATE_EDITABLE) && has(ATSPI_STATE_ENABLED) && has(ATSPI_STATE_VISIBLE) &&
            has(ATSPI_STATE_SHOWING) && !has(ATSPI_STATE_DEFUNCT) ? Result::Valid : Result::Invalid;
    }
    Result poll() {
        if (!pending) return Result::Pending;
        if (std::chrono::steady_clock::now()>=deadline) { cancel();return Result::Unknown; }
        if (!dbus_pending_call_get_completed(pending)) {
            return Result::Pending;
        }
        auto* reply=dbus_pending_call_steal_reply(pending);
        const auto result=decode(reply);
        if (reply) dbus_message_unref(reply);
        dbus_pending_call_unref(pending);pending=nullptr;
        return result;
    }
    ~AccessibleStateProbe() { cancel(); }
};
