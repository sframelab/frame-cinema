#pragma once
// A held key never becomes a new press when input ownership or source changes.
struct ShortcutEdge {
    unsigned source=0;
    bool armed=false;
    bool sample(unsigned next,bool down){
        if(!next||next!=source){source=next;armed=false;}
        if(!next)return false;
        if(!down){armed=true;return false;}
        if(!armed)return false;
        armed=false;return true;
    }
};
