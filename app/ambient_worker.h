#pragma once
#include <filesystem>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <signal.h>
#include <chrono>
#include <cerrno>
// Own a waitable child in the existing Cinema process group. Sampling never
// shares an X connection or a blocking call with pointer/keyboard dispatch.
class AmbientWorker {
    pid_t pid=0;unsigned long current=0;
    std::chrono::steady_clock::time_point retry{};
public:
    void stop() {
        if(pid>0) {
            if(waitpid(pid,nullptr,WNOHANG)==0) {
                kill(pid,SIGKILL);
                while(waitpid(pid,nullptr,0)<0 && errno==EINTR){}
            }
            pid=0;
        }
        current=0;
    }
    void target(unsigned long window) {
        const auto now=std::chrono::steady_clock::now();
        if(window!=current){stop();current=window;retry={};}
        if(pid>0){const auto result=waitpid(pid,nullptr,WNOHANG);if(result==0 || (result<0 && errno==EINTR))return;pid=0;}
        if(!window || now<retry)return;
        retry=now+std::chrono::seconds(3);
        std::error_code error;
        const auto executable=std::filesystem::canonical("/proc/self/exe",error).parent_path()/"ambient_sampler";
        if(error || !std::filesystem::exists(executable,error))return;
        const auto number=std::to_string(window),parent=std::to_string(getpid());pid=fork();
        if(pid==0){execl(executable.c_str(),executable.c_str(),number.c_str(),parent.c_str(),nullptr);_exit(127);}
    }
    ~AmbientWorker(){stop();}
};
