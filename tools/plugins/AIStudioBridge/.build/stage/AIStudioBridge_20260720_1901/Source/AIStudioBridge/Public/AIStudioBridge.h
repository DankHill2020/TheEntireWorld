#pragma once

#include "Modules/ModuleManager.h"

class FAIStudioBridgeModule : public IModuleInterface
{
public:
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;
};
