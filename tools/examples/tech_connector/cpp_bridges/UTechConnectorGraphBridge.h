#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "UTechConnectorGraphBridge.generated.h"

/**
 * UTechConnectorGraphBridge: Automatically generated C++ to Python reflection bridge.
 */
UCLASS(BlueprintType, Blueprintable)
class TECHCONNECTOR_API UTechConnectorGraphBridge : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * WireAnimGraphPoseOutput: Exposed to Unreal Python via UFUNCTION(BlueprintCallable).
	 */
	UFUNCTION(BlueprintCallable, Category = "TechConnector|CppBridge")
	static bool WireAnimGraphPoseOutput(FString AnimInstancePath, FString StateMachineName);

	/**
	 * InjectCharacterMovementNode: Exposed to Unreal Python via UFUNCTION(BlueprintCallable).
	 */
	UFUNCTION(BlueprintCallable, Category = "TechConnector|CppBridge")
	static bool InjectCharacterMovementNode(FString CharacterBPPath, FString InputKey);

};