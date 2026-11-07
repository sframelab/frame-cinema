#pragma once
#include <cmath>
#include <fstream>
#include <string>

// Presentation never changes tracking/placement. A stale scene packet restores
// the complete browser; an intentional settings modal temporarily hides it.
struct PanelPresentation {
    float top=0;
    float requested_top=0;
    bool show=true, interactive=true;
    int error=0;
    void read(const std::string& ipc,const std::string& session,double now) {
        std::string magic,owner;double updated=0;float crop=0;int visible=1,input=1;
        std::ifstream f(ipc+"/presentation.txt");
        show=true;interactive=true;requested_top=0;
        if(!(f>>magic>>owner>>updated>>visible>>input>>crop) || magic!="FCPR1" || owner!=session ||
           !std::isfinite(updated) || now-updated<-.01 || now-updated>.5 || !std::isfinite(crop) || crop<0 || crop>.20 ||
           (visible!=0 && visible!=1) || (input!=0 && input!=1))return;
        show=visible;interactive=input;requested_top=crop;
    }
    template<class API> void apply(API* api,vr::VROverlayHandle_t panel) {
        const vr::VRTextureBounds_t bounds{0,requested_top,1,1-requested_top};
        error=api->SetOverlayTextureBounds(panel,&bounds);
        if(!error)top=requested_top;
        else {
            interactive=false;
            const vr::VRTextureBounds_t full{0,0,1,1};
            if(!api->SetOverlayTextureBounds(panel,&full))top=0;
        }
    }
};
