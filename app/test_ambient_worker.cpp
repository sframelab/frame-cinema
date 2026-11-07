#include "ambient_worker.h"
#include <fstream>
#include <iostream>
#include <thread>
#include <stdexcept>
#include <sys/prctl.h>
static pid_t child(){std::ifstream f("/proc/self/task/"+std::to_string(getpid())+"/children");pid_t p=0;f>>p;return p;}
static void check(bool ok,const char* name){if(!ok)throw std::runtime_error(name);std::cout<<"PASS "<<name<<std::endl;}
int main(int argc,char** argv){
    if(argc!=2)return 2;
    const auto window=std::strtoul(argv[1],nullptr,10);
    AmbientWorker worker;worker.target(window);
    std::this_thread::sleep_for(std::chrono::milliseconds(150));
    pid_t first=child();check(first>0 && kill(first,0)==0,"panel owns one live sampling child");
    kill(first,SIGKILL);std::this_thread::sleep_for(std::chrono::milliseconds(30));worker.target(window);
    check(child()==0,"crashed sampling child is reaped before bounded retry");
    std::this_thread::sleep_for(std::chrono::milliseconds(3000));worker.target(window);
    pid_t second=child();check(second>0 && second!=first,"same-window sampling child restarts after backoff");
    worker.stop();check(child()==0,"stopping panel synchronously reaps its own sampling child");
    {
        AmbientWorker scoped;scoped.target(window);
        check(child()>0,"a new source starts its own sampling worker");
    }
    check(child()==0,"worker destructor leaves no child");
    // Adopt only this fixture's orphan so the death-signal check is reapable.
    prctl(PR_SET_CHILD_SUBREAPER,1);
    int descriptor[2];if(pipe(descriptor))return 3;
    const pid_t owner=fork();
    if(owner==0){
        close(descriptor[0]);AmbientWorker owned;owned.target(window);
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
        pid_t sampler=child();write(descriptor[1],&sampler,sizeof(sampler));
        for(;;)pause();
    }
    close(descriptor[1]);pid_t sampler=0;
    if(read(descriptor[0],&sampler,sizeof(sampler))!=sizeof(sampler))return 4;
    close(descriptor[0]);kill(owner,SIGKILL);waitpid(owner,nullptr,0);
    bool gone=false;
    for(int attempt=0;attempt<100;++attempt){if(waitpid(sampler,nullptr,WNOHANG)==sampler){gone=true;break;}std::this_thread::sleep_for(std::chrono::milliseconds(10));}
    if(!gone && sampler>0){kill(sampler,SIGKILL);waitpid(sampler,nullptr,0);}
    check(gone,"parent death kills and reaps sampler without a lingering process");
    return 0;
}
