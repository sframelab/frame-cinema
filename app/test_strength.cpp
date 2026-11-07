#define main baseline_test_main
#include "test_temporal.cpp"
#undef main
int main(){
    auto rgb=picture();auto truth=geometry();
    double jitter[3]{},separation[3]{};std::vector<float> previous[3];DepthTemporal filters[3];
    std::vector<double> costs;
    for(int t=0;t<36;++t){
        auto raw=truth;
        for(int y=0;y<H;++y)for(int x=0;x<W;++x){
            int k=y*W+x;
            raw[k]+=.025f*std::sin(x*.63f+y*.71f+t*1.9f)+.016f*std::sin(x*.05f+y*.07f+t*1.3f);
        }
        for(int mode=1;mode<=3;++mode){
            auto v=raw;auto start=std::chrono::steady_clock::now();
            filters[mode-1].apply(v,rgb,W,H,1,10+t/30.,1,1,mode);
            if(mode==3)costs.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());
            if(t>8){
                for(int y=20;y<H-20;++y)for(int x=20;x<W-20;++x){int k=y*W+x;jitter[mode-1]+=std::abs(v[k]-previous[mode-1][k]);}
                separation[mode-1]+=v[100*W+150]-v[100*W+60];
            }
            previous[mode-1]=v;
        }
    }
    assert(jitter[1]<jitter[0]*.82 && jitter[2]<jitter[0]*.76);
    assert(separation[1]>separation[0]*.97 && separation[2]>separation[0]*.97);
    // Strong should keep substantially more binocular separation than Subtle.
    assert(3*separation[2]>2.8*separation[0]);
    DepthTemporal moving;double error=0;
    for(int t=0;t<10;++t){
        auto expected=geometry(t*4),v=expected;
        moving.apply(v,picture(t*4),W,H,2,20+t/30.,1,1,3);
        for(int y=48;y<172;++y)for(int x=106+t*4;x<115+t*4;++x)error=std::max(error,double(std::abs(v[y*W+x]-expected[y*W+x])));
    }
    assert(error<.055);
    auto flat=std::vector<float>(W*H,.5f);moving.apply(flat,rgb,W,H,3,30,1,1,3);
    for(auto v:flat)assert(std::abs(v-.5f)<1e-6);
    std::sort(costs.begin()+2,costs.end());
    printf("{\"medium_jitter_vs_old_medium\":%.5f,\"strong_jitter_vs_old_strong\":%.5f,\"strong_separation_vs_subtle\":%.5f,\"moving_edge_error\":%.5f,\"strong_cpu_median_ms\":%.3f}\n",jitter[1]/jitter[0],jitter[2]/jitter[0],3*separation[2]/separation[0],error,costs[18]);
}
