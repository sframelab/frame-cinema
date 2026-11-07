#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace cinema_stereo {
// Causal depth stabilization. Every call starts with a new prediction and its
// immutable current color. History is motion-aligned and rejected at reveals,
// cuts, bad matches, changed source/configuration, and presentation gaps.
class DepthTemporal {
    static constexpr int stride=3;
    struct Flow {float x=0,y=0,error=1;};
    std::vector<float> prior_depth,prior_gray,prior_broad;
    std::vector<unsigned char> prior_color;
    uint64_t revision=0;double then=0;int width=0,height=0;
    static float sample(const std::vector<float>& a,int w,int h,float x,float y){
        x=std::clamp(x,0.f,float(w-1));y=std::clamp(y,0.f,float(h-1));
        int ix=int(x),iy=int(y),jx=std::min(ix+1,w-1),jy=std::min(iy+1,h-1);
        float ax=x-ix,ay=y-iy;
        return (a[iy*w+ix]*(1-ax)+a[iy*w+jx]*ax)*(1-ay)+(a[jy*w+ix]*(1-ax)+a[jy*w+jx]*ax)*ay;
    }
    static float match(const std::vector<float>& a,const std::vector<float>& b,int w,int h,int x,int y,int dx,int dy){
        if(x+dx<2||y+dy<2||x+dx>=w-2||y+dy>=h-2)return 1;
        float sum=0,squared=0;
        for(int j=-2;j<=2;++j)for(int i=-2;i<=2;++i){
            float d=a[(y+j)*w+x+i]-b[(y+j+dy)*w+x+i+dx];sum+=d;squared+=d*d;
        }
        // Permit modest exposure changes without confusing them with motion.
        return std::max(0.f,squared/25-sum*sum/(25*25)*.85f);
    }
    static std::vector<Flow> motion(const std::vector<float>& a,const std::vector<float>& b,int w,int h,int nw,int nh){
        std::vector<Flow> out(nw*nh);
        #pragma omp parallel for num_threads(2) schedule(static)
        for(int gy=0;gy<nh;++gy)for(int gx=0;gx<nw;++gx){
            int x=2+gx*stride,y=2+gy*stride,bx=0,by=0;
            auto score=[&](int dx,int dy){return match(a,b,w,h,x,y,dx,dy)+.0000005f*(dx*dx+dy*dy);};
            float best=score(0,0);
            for(int step:{4,2,1}){
                int ox=bx,oy=by;
                for(int j=-1;j<=1;++j)for(int i=-1;i<=1;++i){
                    int dx=ox+i*step,dy=oy+j*step;float e=score(dx,dy);
                    if(e<best){best=e;bx=dx;by=dy;}
                }
            }
            float c=match(a,b,w,h,x,y,bx,by);
            auto fraction=[&](float minus,float plus){float d=minus+plus-2*c;return c>1e-10f&&d>1e-8f?std::clamp(.5f*(minus-plus)/d,-.5f,.5f):0.f;};
            out[gy*nw+gx]={bx+fraction(match(a,b,w,h,x,y,bx-1,by),match(a,b,w,h,x,y,bx+1,by)),
                          by+fraction(match(a,b,w,h,x,y,bx,by-1),match(a,b,w,h,x,y,bx,by+1)),std::sqrt(c)};
        }
        return out;
    }
    static Flow flow_at(const std::vector<Flow>& a,int w,int h,float x,float y){
        x=std::clamp((x-2)/stride,0.f,float(w-1));y=std::clamp((y-2)/stride,0.f,float(h-1));
        int ix=int(x),iy=int(y);float ax=x-ix,ay=y-iy;Flow out{0,0,0};
        for(int j=0;j<2;++j)for(int i=0;i<2;++i){
            float weight=(i?ax:1-ax)*(j?ay:1-ay);const auto& f=a[std::min(iy+j,h-1)*w+std::min(ix+i,w-1)];
            out.x+=f.x*weight;out.y+=f.y*weight;out.error+=f.error*weight;
        }
        return out;
    }
    float color_error(const std::vector<unsigned char>& color,int w,int h,int x,int y,float px,float py) const {
        if(px<0||py<0||px>w-1||py>h-1)return 1;
        int ix=int(px),iy=int(py),jx=std::min(ix+1,w-1),jy=std::min(iy+1,h-1);float ax=px-ix,ay=py-iy,error=0;
        for(int c=0;c<3;++c){
            float previous=(prior_color[(iy*w+ix)*4+c]*(1-ax)+prior_color[(iy*w+jx)*4+c]*ax)*(1-ay)
                +(prior_color[(jy*w+ix)*4+c]*(1-ax)+prior_color[(jy*w+jx)*4+c]*ax)*ay;
            error+=std::abs(color[(y*w+x)*4+c]-previous);
        }
        return error/(3*255);
    }
public:
    struct Statistics {float history_fraction=0,affine_scale=1,affine_shift=0;bool reset=true;} stats;
    void apply(std::vector<float>& current,const std::vector<unsigned char>& color,int w,int h,uint64_t rev,double stamp,float sx=1,float sy=1,int strength=1){
        stats={};int gw=w/4,gh=h/4,nw=(gw-5)/stride+1,nh=(gh-5)/stride+1;
        const bool enhanced=strength>1;
        std::vector<float> broad_history,match_confidence;
        std::vector<float> gray(gw*gh);
        for(int y=0;y<gh;++y)for(int x=0;x<gw;++x){
            float sum=0;for(int j=0;j<4;++j)for(int i=0;i<4;++i){int k=((y*4+j)*w+x*4+i)*4;sum+=(color[k]+2.f*color[k+1]+color[k+2])/(4*255);}
            gray[y*gw+x]=sum/16;
        }
        auto range=std::minmax_element(current.begin(),current.end());
        bool reset=rev!=revision||width!=w||height!=h||then==0||stamp<=then||stamp-then>.15||nw<2||nh<2||*range.second-*range.first<1e-5f;
        if(!reset){
            stats.reset=false;
            auto forward=motion(gray,prior_gray,gw,gh,nw,nh),backward=motion(prior_gray,gray,gw,gh,nw,nh);
            // Validate match cycles at the motion-grid resolution rather than
            // repeating the reverse lookup/square root for every depth pixel.
            for(int y=0;y<nh;++y)for(int x=0;x<nw;++x){
                auto& f=forward[y*nw+x];auto b=flow_at(backward,nw,nh,2+x*stride+f.x,2+y*stride+f.y);
                float cycle=std::hypot(f.x+b.x,f.y+b.y);
                f.error=std::clamp(1-cycle,0.f,1.f)*std::clamp(1-f.error/.065f,0.f,1.f);
            }
            std::vector<float> history(w*h),confidence(w*h);
            if(enhanced)broad_history.resize(w*h);
            auto active=[&](int x,int y){return std::abs((x+.5f)/w-.5f)<sx*.5f&&std::abs((y+.5f)/h-.5f)<sy*.5f;};
            // Reuse the inference runtime's two-thread OpenMP pool. Each row
            // writes disjoint pixels; no history or reduction order changes.
            #pragma omp parallel num_threads(2)
            {
                std::vector<Flow> line(nw);
                #pragma omp for schedule(static)
                for(int y=8;y<h-8;++y){
                    // Bilinear flow is separable. Interpolate its two sparse
                    // rows once, instead of four flow reads per output pixel.
                    float gy=std::clamp(((y-1.5f)/4-2)/stride,0.f,float(nh-1));
                    int iy=int(gy),jy=std::min(iy+1,nh-1);float ay=gy-iy;
                    for(int x=0;x<nw;++x){
                        const auto& a=forward[iy*nw+x];const auto& b=forward[jy*nw+x];
                        line[x]={a.x*(1-ay)+b.x*ay,a.y*(1-ay)+b.y*ay,a.error*(1-ay)+b.error*ay};
                    }
                    for(int x=8;x<w-8;++x){
                        if(!active(x,y))continue;
                        float gx=std::clamp(((x-1.5f)/4-2)/stride,0.f,float(nw-1));
                        int ix=int(gx),jx=std::min(ix+1,nw-1);float ax=gx-ix;
                        const auto& a=line[ix];const auto& b=line[jx];
                        float px=x+4*(a.x*(1-ax)+b.x*ax),py=y+4*(a.y*(1-ax)+b.y*ax);
                        float photo=color_error(color,w,h,x,y,px,py);
                        float c=(a.error*(1-ax)+b.error*ax)*std::clamp(1-photo/.10f,0.f,1.f);
                        confidence[y*w+x]=c;history[y*w+x]=sample(prior_depth,w,h,px,py);
                        if(enhanced && prior_broad.size()==current.size())broad_history[y*w+x]=sample(prior_broad,w,h,px,py);
                    }
                }
            }
            // Relative-depth models can change scale/offset between images.
            // Fit only matched surfaces, robustly; do not smooth raw min/max.
            double scale=1,shift=0,total=0;
            for(int iteration=0;iteration<3;++iteration){
                double sw=0,sa=0,sb=0,saa=0,sab=0;int matches=0;
                for(int y=8;y<h-8;y+=4)for(int x=8;x<w-8;x+=4){
                    int k=y*w+x;if(confidence[k]<.45f)continue;
                    double a=current[k],b=history[k],residual=std::abs(scale*a+shift-b);
                    double weight=confidence[k]*(iteration?std::min(1.,.035/std::max(1e-8,residual)):1.);
                    sw+=weight;sa+=weight*a;sb+=weight*b;saa+=weight*a*a;sab+=weight*a*b;++matches;
                }
                if(matches<40||sw<.12*(w*h/16)||saa-sa*sa/std::max(sw,1.)<sw*.002){scale=1;shift=0;break;}
                double proposed=(sab-sa*sb/sw)/(saa-sa*sa/sw),offset=(sb-proposed*sa)/sw;
                if(proposed<.8||proposed>1.25||std::abs(offset)>.15){scale=1;shift=0;break;}
                scale=proposed;shift=offset;total=sw;
            }
            if(total>0){stats.affine_scale=float(scale);stats.affine_shift=float(shift);}
            std::vector<float> aligned(current.size());
            for(size_t i=0;i<current.size();++i)aligned[i]=std::clamp(float(current[i]*scale+shift),0.f,1.f);
            const float retention=std::min(.86f,float(std::exp(-(stamp-then)/.20)));
            unsigned blended=0;
            #pragma omp parallel for num_threads(2) schedule(static) reduction(+:blended)
            for(int y=0;y<h;++y)for(int x=0;x<w;++x){
                int k=y*w+x;float residual=std::abs(aligned[k]-history[k]);
                float weight=retention*confidence[k]*std::clamp(1-residual*residual/(.12f*.12f),0.f,1.f);
                float lo=aligned[k],hi=lo;
                if(weight>.001f){
                    for(int j=std::max(0,y-1);j<=std::min(h-1,y+1);++j)for(int i=std::max(0,x-1);i<=std::min(w-1,x+1);++i){lo=std::min(lo,aligned[j*w+i]);hi=std::max(hi,aligned[j*w+i]);}
                    ++blended;
                }
                float previous=std::clamp(history[k],lo-.035f,hi+.035f);
                current[k]=aligned[k]+weight*(previous-aligned[k]);
            }
            stats.history_fraction=float(blended)/(w*h);
            if(enhanced)match_confidence=std::move(confidence);
        }
        // Preserve the accepted Subtle path and its history exactly. Extra
        // strength belongs to broad supported shape, not fine depth noise.
        prior_depth=current;
        if(enhanced){
            const int bw=(w+1)/2,bh=(h+1)/2;
            std::vector<float> broad(current.size()),coarse(bw*bh),horizontal(bw*bh),reduced(bw*bh);
            for(int y=0;y<bh;++y)for(int x=0;x<bw;++x){
                int a=std::min(2*y,h-1)*w+std::min(2*x,w-1),b=std::min(2*y+1,h-1)*w+std::min(2*x,w-1);
                reduced[y*bw+x]=(current[a]+current[a+(2*x+1<w)]+current[b]+current[b+(2*x+1<w)])*.25f;
            }
            const float weights[4]={1.f,.88f,.60f,.32f};
            for(int pass=0;pass<2;++pass){
                const auto& input=pass?horizontal:reduced;auto& output=pass?coarse:horizontal;
                #pragma omp parallel for num_threads(2) schedule(static)
                for(int y=0;y<bh;++y)for(int x=0;x<bw;++x){
                    int k=y*bw+x;float sum=0,total=0;
                    for(int j=-3;j<=3;++j){
                        int px=std::clamp(x+(pass?0:j),0,bw-1),py=std::clamp(y+(pass?j:0),0,bh-1);
                        float v=input[py*bw+px],d=(reduced[py*bw+px]-reduced[k])/.09f;
                        // Compact-support range kernel avoids fourteen scalar
                        // divisions per pixel on the headset CPU, and excludes
                        // strong silhouettes completely from the broad average.
                        float range=std::max(0.f,1-d*d);
                        float weight=weights[std::abs(j)]*range*range;sum+=v*weight;total+=weight;
                    }
                    output[k]=sum/total;
                }
            }
            #pragma omp parallel for num_threads(2) schedule(static)
            for(int y=0;y<h;++y)for(int x=0;x<w;++x){
                int k=y*w+x;
                broad[k]=std::clamp(sample(coarse,bw,bh,(x-.5f)*.5f,(y-.5f)*.5f),current[k]-.06f,current[k]+.06f);
            }
            if(!reset && prior_broad.size()==current.size()){
                const float retention=std::min(.94f,float(std::exp(-(stamp-then)/.45)));
                #pragma omp parallel for num_threads(2) schedule(static)
                for(size_t k=0;k<broad.size();++k){
                    float residual=broad_history[k]-broad[k];
                    // This is motion-aligned history, admitted only by the same
                    // bidirectional/color checks as fresh depth. Reveals/cuts
                    // always use the new frame's estimate.
                    float weight=retention*match_confidence[k]*std::clamp(1-residual*residual/(.16f*.16f),0.f,1.f);
                    broad[k]+=weight*std::clamp(residual,-.06f,.06f);
                }
            }
            prior_broad=broad;
            float detail=1.f/std::clamp(strength,1,3);
            #pragma omp parallel for num_threads(2) schedule(static)
            for(size_t k=0;k<current.size();++k)current[k]=current[k]*detail+broad[k]*(1-detail);
        }else prior_broad.clear();
        prior_color=color;prior_gray=std::move(gray);revision=rev;then=stamp;width=w;height=h;
    }
};
}
