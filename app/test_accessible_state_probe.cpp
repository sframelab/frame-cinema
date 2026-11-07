// Runs under dbus-run-session. No desktop, browser profile or account access.
#include "accessible_state_probe.h"
#include <chrono>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>

using Clock=std::chrono::steady_clock;
using Result=AccessibleStateProbe::Result;
static int failures=0;
static void check(bool good,const char* name) {
    std::printf("%s %s\n",good?"PASS":"FAIL",name);if (!good) ++failures;
}
struct Delayed { DBusMessage* request;Clock::time_point due; };
int main() {
    auto* server=dbus_bus_get_private(DBUS_BUS_SESSION,nullptr);
    auto* client=dbus_bus_get_private(DBUS_BUS_SESSION,nullptr);
    if (!server || !client) return 2;
    dbus_connection_set_exit_on_disconnect(server,false);
    dbus_connection_set_exit_on_disconnect(client,false);
    const std::string destination=dbus_bus_get_unique_name(server);
    std::vector<Delayed> waiting;
    long maximum_us=0;
    auto respond=[&](DBusMessage* request) {
        const std::string path=dbus_message_get_path(request);
        auto* reply=path=="/missing"?dbus_message_new_error(request,DBUS_ERROR_UNKNOWN_OBJECT,"Removed fixture"):
            dbus_message_new_method_return(request);
        if (path=="/malformed") {
            const char* value="fixture";dbus_message_append_args(reply,DBUS_TYPE_STRING,&value,DBUS_TYPE_INVALID);
        } else if (path!="/missing") {
            dbus_uint32_t bits[2]{};
            for (auto state:{ATSPI_STATE_EDITABLE,ATSPI_STATE_ENABLED,ATSPI_STATE_VISIBLE,ATSPI_STATE_SHOWING})
                bits[unsigned(state)/32]|=1u<<(unsigned(state)%32);
            if (path=="/hidden") bits[unsigned(ATSPI_STATE_VISIBLE)/32]&=~(1u<<(unsigned(ATSPI_STATE_VISIBLE)%32));
            if (path=="/defunct") bits[unsigned(ATSPI_STATE_DEFUNCT)/32]|=1u<<(unsigned(ATSPI_STATE_DEFUNCT)%32);
            auto* array=bits;
            dbus_message_append_args(reply,DBUS_TYPE_ARRAY,DBUS_TYPE_UINT32,&array,2,DBUS_TYPE_INVALID);
        }
        dbus_connection_send(server,reply,nullptr);dbus_message_unref(reply);dbus_message_unref(request);
    };
    auto pump=[&]() {
        dbus_connection_read_write(server,0);
        while (auto* message=dbus_connection_pop_message(server)) {
            if (dbus_message_is_method_call(message,"org.a11y.atspi.Accessible","GetState")) {
                const bool slow=std::string(dbus_message_get_path(message))=="/slow";
                waiting.push_back({message,Clock::now()+std::chrono::milliseconds(slow?450:0)});
            } else dbus_message_unref(message);
        }
        for (auto it=waiting.begin();it!=waiting.end();) {
            if (Clock::now()>=it->due) { respond(it->request);it=waiting.erase(it); }
            else ++it;
        }
        dbus_connection_read_write_dispatch(client,0);
    };
    auto finish=[&](AccessibleStateProbe& probe) {
        const auto deadline=Clock::now()+std::chrono::seconds(2);
        Result result=Result::Pending;
        while (Clock::now()<deadline && result==Result::Pending) {
            pump();
            const auto start=Clock::now();result=probe.poll();
            const long elapsed=std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-start).count();
            if (elapsed>maximum_us) maximum_us=elapsed;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        return result;
    };
    AccessibleStateProbe probe;
    for (const auto& fixture:std::vector<std::pair<const char*,Result>>{{"/valid",Result::Valid},{"/hidden",Result::Invalid},
            {"/defunct",Result::Invalid},{"/missing",Result::Invalid},{"/malformed",Result::Unknown},{"/slow",Result::Unknown}}) {
        check(probe.start(client,destination.c_str(),fixture.first) && finish(probe)==fixture.second,fixture.first);
    }
    check(probe.start(client,destination.c_str(),"/valid") && finish(probe)==Result::Valid,
        "valid state recovers after a real delayed-reply timeout");
    probe.start(client,destination.c_str(),"/hidden");
    const auto completed_deadline=Clock::now()+std::chrono::milliseconds(100);
    while (!dbus_pending_call_get_completed(probe.pending) && Clock::now()<completed_deadline) {
        pump();std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    const bool completed=dbus_pending_call_get_completed(probe.pending);
    std::this_thread::sleep_for(std::chrono::milliseconds(180));
    check(completed && probe.poll()==Result::Unknown,"completed but unconsumed state expires before it can retire a restored field");
    check(probe.start(client,destination.c_str(),"/valid") && finish(probe)==Result::Valid,
        "fresh valid query succeeds after an unconsumed reply expires");
    probe.start(client,destination.c_str(),"/slow");pump();probe.cancel();
    check(probe.start(client,destination.c_str(),"/valid") && finish(probe)==Result::Valid,
        "replacement target has its own query after cancellation");
    const auto end=Clock::now()+std::chrono::milliseconds(600);
    while (Clock::now()<end) { pump();std::this_thread::sleep_for(std::chrono::milliseconds(1)); }
    check(probe.poll()==Result::Pending && !probe.pending,"late cancelled replies cannot overwrite replacement state");
    check(maximum_us<50000,"polling a delayed reply never blocks for its timeout");
    std::printf("Diagnostic maximum poll microseconds: %ld\n",maximum_us);
    for (auto& item:waiting) dbus_message_unref(item.request);
    probe.cancel();
    for (auto* bus:{client,server}) { dbus_connection_close(bus);dbus_connection_unref(bus); }
    std::printf("Accessible state failures: %d\n",failures);
    return failures?1:0;
}
