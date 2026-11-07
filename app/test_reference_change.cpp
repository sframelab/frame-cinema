#include "native-ui/reference_change.h"
#include <cassert>
#include <iostream>
namespace cp=cinema_placement;
int main(){
    // Exact float32 values observed on a Steam Frame, 2026-10-09.
    const cp::Matrix actual={{{.996502518654f,0,.0835625678301f,-.0284614805132f},
        {0,1,0,1.09019517899f},{-.0835625678301f,0,.996502518654f,.0952090099454f}}};
    assert(cp::rigid(actual));
    assert(cp::angle(actual,actual)>1e-5); // Reproduces the false reset.
    assert(!cinema_reference_changed(actual,actual));
    auto tiny=actual;tiny.m[0][0]=std::nextafter(tiny.m[0][0],1.f);
    assert(!cinema_reference_changed(tiny,actual));
    auto moved=actual;moved.m[0][3]+=.00002f;
    assert(cinema_reference_changed(moved,actual));
    auto rotation=cp::identity();double a=.0001;
    rotation.m[0][0]=rotation.m[2][2]=std::cos(a);
    rotation.m[0][2]=std::sin(a);rotation.m[2][0]=-std::sin(a);
    assert(cinema_reference_changed(cp::multiply(rotation,actual),actual));
    cp::Bridge bridge("test");cp::Packet packet;
    packet.session="test";packet.generation=packet.revision=1;packet.width=30;
    packet.tracked=1;packet.head=cp::identity();packet.screen=cp::identity();packet.screen.m[2][3]=-26;
    vr::TrackedDevicePose_t hmd{};hmd.bPoseIsValid=hmd.bDeviceIsConnected=true;
    hmd.eTrackingResult=vr::TrackingResult_Running_OK;hmd.mDeviceToAbsoluteTracking=cp::identity();
    bool ready=false;
    for(int i=0;i<14;++i){
        double now=100+i*.03;packet.sequence=i+1;packet.created=now-.005;
        if(cinema_reference_changed(actual,actual))bridge.invalidate(now);
        ready=bridge.update(packet,hmd,now,true);
    }
    assert(ready);assert(bridge.width==30);
    bridge.invalidate(101);packet.created=100.99;
    assert(!bridge.update(packet,hmd,101,true)); // Real resets still reject stale placement.
    std::cout<<"PASS unchanged float32 reference, subthreshold jitter, real rotation/translation, calibration and stale-reset rejection\n";
}
