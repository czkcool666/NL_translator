#include "SVF-LLVM/LLVMUtil.h"
#include "SVF-LLVM/SVFIRBuilder.h"
#include "MemoryModel/PointerAnalysisImpl.h"
#include "DDA/ContextDDA.h"
#include "DDA/DDAClient.h"
#include "Util/Options.h"
#include "SVFIR/SVFFileSystem.h"
#include <iostream>
#include <string>
#include <map>
#include <set>
#include <vector>
#include <fstream>
#include <nlohmann/json.hpp>

using namespace llvm;
using namespace std;
using namespace SVF;
std::map<std::string, std::vector<std::string>> irContents;

/// Function parameter alias analysis client
class FunctionParamAliasAnalyzer : public DDAClient {
   
    // Store SVFIR reference
    SVFIR* pag;
    typedef std::map<const SVFFunction*, std::set<std::pair<NodeID, NodeID>>> FunParamTwoPointer;
    FunParamTwoPointer funParamTwoPointer;
    typedef std::map<const SVFFunction*, std::set<NodeID>> FunParamOnePointer;
    FunParamOnePointer funParamOnePointer;
    
    std::map<const SVFFunction*, int> funcCallLevel;

    struct ParamPointsToInfo {
        NodeID paramID;                   
        std::string funcName;             
        std::string paramName;             
        std::map<const CallICFGNode*, std::pair<NodeID, std::string>> callerInfo; 
        std::map<const CallICFGNode*, std::string> callStmts;  
        std::map<const CallICFGNode*, std::pair<std::string, std::string>> pointsToInfo; 

        std::map<const CallICFGNode*, std::vector<std::vector<NodeID>>> reversePaths; 
        std::map<const CallICFGNode*, std::vector<std::vector<NodeID>>> forwardPaths; 

        std::string mutabilityResult;     
        std::string nullabilityResult;    

        std::string ownershipResult;     
        std::string structMemberUsage;
    };

    typedef std::map<const SVFFunction*, std::map<NodeID, ParamPointsToInfo>> FuncParamPointsToMap;
    FuncParamPointsToMap funcParamPointsToMap;



    struct ReturnPointsToInfo {
        NodeID returnID;                   
        std::string funcName;             
        std::string returnName;            
        
        std::string mutabilityResult;     
        std::string nullabilityResult;    

        std::string ownershipResult;     
        std::string lifeResult;     
    };

    typedef std::map<const SVFFunction*, std::map<NodeID, ReturnPointsToInfo>> FuncReturnPointsToMap;
    FuncReturnPointsToMap funcReturnPointsToMap;

    struct NodeInfo {
        NodeID id;
        std::string type;        
        std::string description; 
        bool hasValue;           
        std::string valueName;   
        std::string valueType;  
        int line;
        std::string file_name;    
    };
    struct EdgeInfo {
        NodeID srcId;
        NodeID dstId;
        std::string type;        
        std::string description;
    };


public:

    FunctionParamAliasAnalyzer(SVFIR* p) : DDAClient(p->getModule()), pag(p) {
        // collectFunctionPointerParams();
    }
    
    virtual ~FunctionParamAliasAnalyzer() {}
    
    /// Get SVFIR
    inline SVFIR* getPAG() const {
        return pag;
    }

    void buildCallGraphLevels(ContextDDA* pta) {
        PTACallGraph* callgraph = pta->getPTACallGraph();
        callgraph->dump("callgraph");
        if (!callgraph) return;
        
        std::set<const SVFFunction*> leafFuncs;
        std::map<const SVFFunction*, std::set<const SVFFunction*>> calleesMap;
        
        std::map<const SVFFunction*, std::set<const SVFFunction*>> callersMap;
        
        for (auto it = callgraph->begin(), eit = callgraph->end(); it != eit; ++it) {
            PTACallGraphNode* node = it->second;
            const SVFFunction* func = node->getFunction();

            if (func->isDeclaration()) continue;
            
            std::set<const SVFFunction*> callees;
            bool onlySelfRecursive = true; 
            
            for (auto eit = node->OutEdgeBegin(), eeit = node->OutEdgeEnd(); eit != eeit; ++eit) {
                PTACallGraphEdge* edge = *eit;
                PTACallGraphNode* dstNode = edge->getDstNode();
                const SVFFunction* callee = dstNode->getFunction();
                
                if (callee->isDeclaration()) continue;
                
                if (callee != func) {
                    onlySelfRecursive = false; 
                }
                
                callees.insert(callee);
                
                callersMap[callee].insert(func);
            }
            
            calleesMap[func] = callees;
            
            if (callees.empty() || (onlySelfRecursive && callees.size() == 1)) {
                leafFuncs.insert(func);
                funcCallLevel[func] = 0; 
            }
        }
        
        std::set<const SVFFunction*> processedFuncs;
        
        std::queue<const SVFFunction*> workList;
        for (const SVFFunction* leaf : leafFuncs) {
            workList.push(leaf);
        }
        
        while (!workList.empty()) {
            const SVFFunction* current = workList.front();
            workList.pop();
            
            if (processedFuncs.find(current) != processedFuncs.end()) {
                continue;
            }
            
            processedFuncs.insert(current);
            int currentLevel = funcCallLevel[current];

            for (const SVFFunction* caller : callersMap[current]) {
                // Skip external functions
                if (caller->isDeclaration()) continue;
                
                // Skip self-recursive calls when updating levels
                if (caller == current) continue;
                
                // Update caller's level if needed
                if (funcCallLevel.find(caller) == funcCallLevel.end() || 
                    funcCallLevel[caller] <= currentLevel) {
                    funcCallLevel[caller] = currentLevel + 1;
                    workList.push(caller);
                }
            }
        }
    
        std::map<int, std::vector<std::string>> levelToFuncs;
        int maxLevel = 0;
        
        for (const auto& pair : funcCallLevel) {
            const SVFFunction* func = pair.first;
            int level = pair.second;
            
            if (level > maxLevel) maxLevel = level;
            levelToFuncs[level].push_back(func->getName());
        }
        
        for (int level = 0; level <= maxLevel; level++) {
            std::cout << "level " << level << " (共 " << levelToFuncs[level].size() << " Functions):" << std::endl;
            for (const auto& funcName : levelToFuncs[level]) {
                std::cout << "  " << funcName << std::endl;
            }
        }    
    }
    

    std::string isSameObject(NodeID actualArgID, const SVFFunction* caller, bool fieldSensitive) {
        if (!caller) return "not_caller_param";

        int callerLineStart = -1;
        const Value* llvmFunc = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(caller);
        if (const Function* F = dyn_cast<Function>(llvmFunc)) {
            if (F->getSubprogram()) {
                DISubprogram* SP = F->getSubprogram();
                callerLineStart = SP->getLine();
            }
        }
        if (callerLineStart == -1) {
            std::cout << "caller function line start is -1 " << caller->getName() << std::endl;
            return "not_caller_param";
        }

        std::vector<NodeID> callerParamIDs;
        for (unsigned i = 0; i < caller->arg_size(); i++) {
            const SVFArgument* arg = caller->getArg(i);
            if (arg->getType()->isPointerTy()) {
                NodeID paramID = pag->getValueNode(arg);
                callerParamIDs.push_back(paramID);
            }
        }

        int actualLine = -1;
        const PAGNode* node = pag->getGNode(actualArgID);
        std::string desc = node->toString();
        size_t lnPos = desc.find("\"ln\": ");
        if (lnPos != std::string::npos) {
            lnPos += 6; 
            size_t commaPos = desc.find(",", lnPos);
            size_t bracePos = desc.find("}", lnPos);
            size_t endPos = std::min(commaPos != std::string::npos ? commaPos : desc.length(), 
                                    bracePos != std::string::npos ? bracePos : desc.length());
            actualLine = std::stoi(desc.substr(lnPos, endPos - lnPos));
        }
        if (actualLine == -1) {
            std::cout << "actualArgID line start is -1 " << actualArgID << std::endl;
            return "not_caller_param";
        }

        std::map<NodeID, NodeInfo> allNodes;
        std::map<std::pair<NodeID, NodeID>, EdgeInfo> allEdges;
        
        std::map<NodeID, NodeID> parent;
        std::map<NodeID, std::string> edgeType;
        
        std::map<NodeID, bool> hasFieldAccess;
        
        NodeInfo startNodeInfo = getNodeInfo(node);
        allNodes[actualArgID] = startNodeInfo;
        hasFieldAccess[actualArgID] = false; 
        
        std::queue<NodeID> worklist;
        std::set<NodeID> visited;
        
        worklist.push(actualArgID);
        visited.insert(actualArgID);
        
        std::set<NodeID> matchingParams;
        
        while (!worklist.empty()) {
            NodeID curId = worklist.front();
            worklist.pop();
            
            for (NodeID paramID : callerParamIDs) {
                if (curId == paramID) {
                    const PAGNode* pagNode = pag->getGNode(curId);
                    const SVFValue* svfVal = pagNode->getValue();
                    const Value* llvmVal = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(svfVal);
                    std::string curIdname = llvmVal->getName().str();
                    if (fieldSensitive) {
                        if (!hasFieldAccess[curId]) {
                            std::cout << "Find: NodeID = " << curIdname + ":" + std::to_string(paramID) << std::endl;
                            return curIdname + ":" + std::to_string(paramID);
                        } else {
                            std::cout << "found function parameter: NodeID = " << paramID << std::endl;
                        }
                    } else {
                        std::cout << "Find: NodeID = " << curIdname + ":" + std::to_string(paramID) << std::endl;
                        return curIdname + ":" + std::to_string(paramID);
                    }
                }
            }
            
            const PAGNode* curNode = pag->getGNode(curId);
            if (!curNode) continue;
            
            for (const PAGEdge* edge : curNode->getInEdges()) {
                NodeID srcId = edge->getSrcID();
                std::string edgeTypeStr = getEdgeTypeStr(edge);
                
                const PAGNode* srcNode = pag->getGNode(srcId);
                if (!srcNode) continue;
                
                NodeInfo srcNodeInfo = getNodeInfo(srcNode);
                int srcNodeLine = srcNodeInfo.line;
                
                bool isStopTag = false;
                if (srcNodeLine < callerLineStart || srcNodeLine > actualLine) {
                    isStopTag = true;
                    continue;
                }
                
                EdgeInfo edgeInfo;
                edgeInfo.srcId = srcId;
                edgeInfo.dstId = curId;
                edgeInfo.type = edgeTypeStr;
                edgeInfo.description = edge->toString();
                allEdges[{srcId, curId}] = edgeInfo;
                
                allNodes[srcId] = srcNodeInfo;
                
                if (visited.find(srcId) == visited.end()) {
                    visited.insert(srcId);
                    worklist.push(srcId);
                    parent[srcId] = curId;
                    edgeType[srcId] = edgeTypeStr;
                    bool currentHasFieldAccess = hasFieldAccess[curId]; 
                    if (edgeTypeStr == "GepObjPN" || edgeTypeStr == "GepValPN" || edge->getEdgeKind() == SVFStmt::Gep) {
                        currentHasFieldAccess = true; 
                        std::cout << "Detect field access operation: " << srcId << " -> " << curId << " (type: " << edgeTypeStr << ")" << std::endl;
                    }
                    
                    hasFieldAccess[srcId] = currentHasFieldAccess;
                }
            }
        }

        return "not_caller_param";
    }


    // Object: function pointer parameters and return.
    void startAnalysis_BottomUp(ContextDDA* pta) {
        

        buildCallGraphLevels(pta);
        ICFG* icfg = pag->getICFG();
        icfg->dump("icfg");
        pag->dump("pag");
    
        // Find the max call level
        int maxLevel = 0;
        for (const auto& pair : funcCallLevel) {
            maxLevel = std::max(maxLevel, pair.second);
        }
        
        // Process functions bottom-up (from leaf to root)
        for (int level = 0; level <= maxLevel; level++) {
            for (const auto& pair : funcCallLevel) {
                const SVFFunction* func = pair.first;
                int funcLevel = pair.second;

                // Skip if not at current level or already analyzed
                if (funcLevel != level) continue;

                // Skip function declarations
                if (func->isDeclaration()) continue;
                std::cout << "func: " << func->getName() << " level: " << funcLevel << std::endl;
                analyzeParam_pointTo(pta, func);
                analyzeParam_Mutability_Nullability(pta, func);
                analyzeParam_Ownership(pta, func);
                analyzeStructMemberUsage(pta, func);
                analyzeReturn_Mutability_Nullability(pta, func);
                analyzeReturn_Ownership_life(pta, func);


            }
        }
    }

    void analyzeReturn_Mutability_Nullability(ContextDDA* pta, const SVFFunction* func) {        
        PTACallGraph* callgraph = pta->getPTACallGraph();
        
        bool hasPointerReturn = false;
        std::map<NodeID, ReturnPointsToInfo> returnPointsToMap;
        
        const SVFType* retType = func->getReturnType();
        if (retType->isPointerTy()) {
            hasPointerReturn = true;
        }
        if (!hasPointerReturn) return;
        std::cout << "func: " << func->getName() << " hasPointerReturn: " << hasPointerReturn << std::endl;

        ReturnPointsToInfo returnInfo;
        returnInfo.returnID = 0; 
        returnInfo.funcName = func->getName();
        returnInfo.returnName = "return_value";
        returnInfo.mutabilityResult = "Immutable"; 
        returnInfo.nullabilityResult = "Not_nullable"; 
        
        PTACallGraphNode* callGraphNode = callgraph->getCallGraphNode(func);
        if (!callGraphNode) return;

        for (PTACallGraphEdge* edge : callGraphNode->getInEdges()) {
            for (auto it = edge->getDirectCalls().begin(); it != edge->getDirectCalls().end(); ++it) {  
                const CallICFGNode* callsite = *it;
                const SVFFunction* caller = callsite->getCaller();
                if (caller->isDeclaration()) continue;
                analyzeCallsiteReturnValue(callsite, returnInfo);
            }
        }
        if (returnInfo.returnID != 0) {
            returnPointsToMap[returnInfo.returnID] = returnInfo;
            funcReturnPointsToMap[func] = returnPointsToMap;
        } else{
            returnInfo.returnID = -1; 
            returnPointsToMap[returnInfo.returnID] = returnInfo;
            funcReturnPointsToMap[func] = returnPointsToMap;
        }
    }

    void analyzeCallsiteReturnValue(const CallICFGNode* callsite, ReturnPointsToInfo& returnInfo) {
        const SVFFunction* caller = callsite->getCaller();

        NodeID callsiteNodeID = 0;        
        const SVFInstruction* callInst = callsite->getCallSite();
        if (!callInst) return;
        std::cout << "Call instruction: " << callInst->toString() << std::endl;
        NodeID callValueNodeID = 0;
        if (pag->hasValueNode(callInst)) {
            callValueNodeID = pag->getValueNode(callInst);
        } else {
            return;
        }
        
        if (returnInfo.returnID == 0) returnInfo.returnID = callValueNodeID;

        std::set<NodeID> relatedNodes;
        std::queue<NodeID> worklist;
        std::set<NodeID> visited;
        
        worklist.push(callValueNodeID);
        visited.insert(callValueNodeID);
        relatedNodes.insert(callValueNodeID);
        
        const PAGNode* returnNode = pag->getGNode(callValueNodeID);
        
        std::cout << "Return value node info: " << returnNode->toString() << std::endl;
        
        while (!worklist.empty()) {
            NodeID curID = worklist.front();
            worklist.pop();
            
            const PAGNode* curNode = pag->getGNode(curID);
            if (!curNode) continue;
            
            for (const PAGEdge* edge : curNode->getOutEdges()) {
                NodeID dstID = edge->getDstID();
                
                if (visited.find(dstID) != visited.end()) continue;
                
                visited.insert(dstID);
                relatedNodes.insert(dstID);
                std::cout << "Edge: " << edge->toString() << std::endl;
                std::cout << "Return dstID: " << dstID << std::endl;

                const PAGNode* dstNode = pag->getGNode(dstID);                
                if (relatedNodes.size() < 100) { 
                    worklist.push(dstID);
                }
            }
        }
        
        std::cout << "Found " << relatedNodes.size() << " related nodes" << std::endl;

        std::pair<bool, bool> modified_nullable_result = analyzeRelatedNodes(relatedNodes, callValueNodeID);
        bool isModified = modified_nullable_result.first;
        bool isNullable = modified_nullable_result.second;
        if (isModified) {
            returnInfo.mutabilityResult = "Mutable";
        }
        if (isNullable) {
            returnInfo.nullabilityResult = "Nullable";
        }
        
        std::cout << "Callsite analysis result - Modified: " << isModified
                  << ", Nullable: " << isNullable << std::endl;

    }


    std::pair<bool, bool> analyzeRelatedNodes(const std::set<NodeID>& relatedNodes, NodeID originalNode) {
        std::cout << "Analyzing " << relatedNodes.size() << " related nodes for modification and nullability" << std::endl;
        
        bool isModified = false;
        bool isNullable = false;
        
        for (NodeID nodeID : relatedNodes) {
            const PAGNode* node = pag->getGNode(nodeID);
            if (!node) continue;
            for (const PAGEdge* inEdge : node->getInEdges()) {
                
                if (const CopyStmt* copy = SVFUtil::dyn_cast<CopyStmt>(inEdge)) {
                    NodeID lhsID = copy->getLHSVarID();
                    NodeID rhsID = copy->getRHSVarID();
                
                    if (!isModified && relatedNodes.count(lhsID) && !relatedNodes.count(rhsID)) {
                        std::cout << "CopyStmt: " << copy->toString() << std::endl;
                        isModified = true;
                    }
                    if (!isNullable && lhsID == nodeID && pag->isNullPtr(rhsID)) {
                        isNullable = true;
                    }
                }

                else if (const StoreStmt* store = SVFUtil::dyn_cast<StoreStmt>(inEdge)) {
                    NodeID lhsID = store->getLHSVarID(); 
                    NodeID rhsID = store->getRHSVarID(); 
                    
                    if (!isModified && relatedNodes.count(lhsID)) {
                        const PAGNode* lhsNode = pag->getGNode(lhsID);
                        const PAGNode* rhsNode = pag->getGNode(rhsID);
                        
                        bool isStoringToAddress = false;
                        if (lhsNode && rhsNode) {
                            if (lhsNode->getType() && lhsNode->getType()->isPointerTy()) {
                                if (rhsID == originalNode || relatedNodes.count(rhsID)) {
                                    isStoringToAddress = true;
                                }
                            }
                        }
                        
                        if (!isStoringToAddress) {
                            std::cout << "StoreStmt: " << store->toString() << std::endl;
                            isModified = true;
                        } else {
                            std::cout << "Skipping StoreStmt (storing to address): " << store->toString() << std::endl;
                        }
                    }
                    
                    if (!isNullable && pag->isNullPtr(rhsID) && relatedNodes.count(lhsID)) {
                        isNullable = true;
                    }
                }

                else if (const LoadStmt* load = SVFUtil::dyn_cast<LoadStmt>(inEdge)) {
                    if (isModified) continue;
                    NodeID srcID = load->getRHSVarID(); 
                    NodeID dstID = load->getLHSVarID();
                    
                    if (relatedNodes.count(srcID)) {
                        const PAGNode* dstNode = pag->getGNode(dstID);
                        if (dstNode) {
                            for (const PAGEdge* dstOutEdge : dstNode->getOutEdges()) {
                                if (const StoreStmt* subsequentStore = SVFUtil::dyn_cast<StoreStmt>(dstOutEdge)) {
                                    NodeID storeLhsID = subsequentStore->getLHSVarID();
                                    NodeID storeRhsID = subsequentStore->getRHSVarID();
                                    
                                    bool isStoringLoadedValueToAddress = false;
                                    if (storeRhsID == dstID) {
                                        const PAGNode* storeLhsNode = pag->getGNode(storeLhsID);
                                        if (storeLhsNode && storeLhsNode->getType() && storeLhsNode->getType()->isPointerTy()) {
                                            isStoringLoadedValueToAddress = true;
                                        }
                                    }
                                    
                                    if (!isStoringLoadedValueToAddress) {
                                        std::cout << "Subsequent StoreStmt: " << subsequentStore->toString() << std::endl;
                                        isModified = true;
                                        break;
                                    } else {
                                        std::cout << "Skipping Subsequent StoreStmt (storing loaded value to address): " << subsequentStore->toString() << std::endl;
                                    }
                                }
                            }
                        }
                    }
                }
                
                else if (const CmpStmt* cmp = SVFUtil::dyn_cast<CmpStmt>(inEdge)) {
                    if (isNullable) continue;
                    bool hasReturnValue = false;
                    bool hasNull = false;
                    
                    for (u32_t i = 0; i < cmp->getOpVarNum(); i++) {
                        NodeID opId = cmp->getOpVarID(i);
                        if (relatedNodes.count(opId) || opId == originalNode) {
                            hasReturnValue = true;
                        }
                        if (pag->isNullPtr(opId)) {
                            hasNull = true;
                        }
                    }
                    
                    if (hasReturnValue && hasNull) {
                        isNullable = true;
                    }
                }

                else if (const GepStmt* gep = SVFUtil::dyn_cast<GepStmt>(inEdge)) {
                    if (isModified) continue;
                    NodeID baseID = gep->getRHSVarID(); 
                    NodeID gepResultID = gep->getLHSVarID();
                    
                    if (relatedNodes.count(baseID)) {
                        const PAGNode* gepResultNode = pag->getGNode(gepResultID);
                        if (gepResultNode) {
                            for (const PAGEdge* gepOutEdge : gepResultNode->getOutEdges()) {
                                if (const StoreStmt* fieldStore = SVFUtil::dyn_cast<StoreStmt>(gepOutEdge)) {
                                    if (fieldStore->getLHSVarID() == gepResultID) {
                                        isModified = true;
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            for (const PAGEdge* outEdge : node->getOutEdges()) {
                if (const BranchStmt* branch = SVFUtil::dyn_cast<BranchStmt>(outEdge)) {
                    if (isNullable) continue;
                    const SVFVar* condVar = branch->getCondition();
                    if (condVar) {
                        const SVFValue* condValue = condVar->getValue();
                        if (condValue && pag->hasValueNode(condValue)) {
                            NodeID condID = pag->getValueNode(condValue);
                            
                            std::set<NodeID> condVisited;
                            std::queue<NodeID> condWorklist;
                            condWorklist.push(condID);
                            condVisited.insert(condID);
                            
                            bool foundReturnValueInCondition = false;
                            while (!condWorklist.empty() && !foundReturnValueInCondition) {
                                NodeID curCondID = condWorklist.front();
                                condWorklist.pop();
                                
                                if (relatedNodes.count(curCondID) || curCondID == originalNode) {
                                    foundReturnValueInCondition = true;
                                    break;
                                }
                                
                                const PAGNode* curCondNode = pag->getGNode(curCondID);
                                if (curCondNode) {
                                    for (const PAGEdge* condInEdge : curCondNode->getInEdges()) {
                                        NodeID srcID = condInEdge->getSrcID();
                                        if (condVisited.find(srcID) == condVisited.end()) {
                                            condWorklist.push(srcID);
                                            condVisited.insert(srcID);
                                        }
                                    }
                                }
                            }
                            
                            if (foundReturnValueInCondition) {
                                isNullable = true;
                            }
                        }
                    }
                }
            }
        }

        return std::make_pair(isModified, isNullable);
    }

    std::pair<int, int> getFuncLineRange(const SVFFunction* func) {
        int funcLineStart = -1;
        int funcLineEnd = 0;

        const Value* llvmFunc = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(func);
        if (const Function* F = dyn_cast<Function>(llvmFunc)) {
            if (F->getSubprogram()) {
                DISubprogram* SP = F->getSubprogram();
                funcLineStart = SP->getLine();

                for (const BasicBlock &BB : *F) {
                    for (const Instruction &I : BB) {
                        if (const DebugLoc &DL = I.getDebugLoc()) {
                            if (DL.getLine() > funcLineEnd) {
                                funcLineEnd = DL.getLine();
                            }
                        }
                    }
                }
            }
        }
        return std::make_pair(funcLineStart, funcLineEnd);
    }

    void analyzeReturn_Ownership_life(ContextDDA* pta, const SVFFunction* func) {
        if (funcReturnPointsToMap.find(func) == funcReturnPointsToMap.end()) return; 
        std::cout << "analyzeReturn_Ownership: " << func->getName() << std::endl;
        const SVFVar* funRetVar = pag->getFunRet(func);
        NodeID funRetNodeID = funRetVar->getId();

        std::cout << "Function return node ID: " << funRetNodeID << std::endl;
        std::string ownershipResult = "Borrowed"; 

        std::set<NodeID> allRelatedNodes = getAllRelatedNodes(funRetNodeID, func);
        bool is_malloc = isAllocationSource(allRelatedNodes); 
        if (is_malloc) ownershipResult = "Owning";

        if(!is_malloc) {
            std::string fromFuncName = getFunctionCallFromInEdges(allRelatedNodes);
            if (fromFuncName != "") ownershipResult = fromFuncName;
        }

        std::string lifeResult = "No_Depends"; 
        std::string tempLifeResult = getLifeResult(allRelatedNodes);
        
        if (!tempLifeResult.empty()) {
            lifeResult = tempLifeResult;
        }

        std::map<NodeID, ReturnPointsToInfo>& returnPointsToMap = funcReturnPointsToMap[func];
        
        for (auto& returnPair : returnPointsToMap) {
            ReturnPointsToInfo& returnInfo = returnPair.second;
            returnInfo.ownershipResult = ownershipResult;
            returnInfo.lifeResult = lifeResult;
            std::cout << "Set ownership result for callsite node " << returnPair.first << ": " << ownershipResult << std::endl;
        }
        std::cout << "=== Finished analyzing function " << func->getName() << " -> " << ownershipResult << " ===" << std::endl;
    }
    
    std::pair<std::string, std::string> getGepStructInfo(const PAGEdge* edge) {
        if (edge->getEdgeKind() != PAGEdge::Gep) {
            return {"", ""};
        }
        
        const GepStmt* gepStmt = SVFUtil::dyn_cast<GepStmt>(edge);
        if (!gepStmt) {
            return {"", ""};
        }
        
        const AccessPath& ap = gepStmt->getAccessPath();
        
        const SVFVar* srcVar = gepStmt->getRHSVar();
        if (!srcVar || !srcVar->getValue()) {
            return {"", ""};
        }
        
        const SVFValue* value = srcVar->getValue();
        if (!value) {
            return {"", ""};
        }
        
        std::string structType = "";
        std::string fieldInfo = "";
        if (const SVFInstruction* inst = SVFUtil::dyn_cast<SVFInstruction>(value)) {
            std::string instStr = inst->toString();
            size_t structPos = instStr.find("%struct.");
            if (structPos != std::string::npos) {
                size_t typeStart = structPos;
                size_t typeEnd = instStr.find_first_of(" ,*)", typeStart);
                if (typeEnd != std::string::npos) {
                    structType = instStr.substr(typeStart, typeEnd - typeStart);
                }
            }
        }

        if (ap.isConstantOffset()) {
            fieldInfo = "field_" + std::to_string(ap.getConstantStructFldIdx());
        } else {
            fieldInfo = "variant_field";
        }
        
        return {structType, fieldInfo};
    }

    std::set<NodeID> getAllRelatedNodes(NodeID funRetNodeID, const SVFFunction* func) {
        std::cout << "\n==== Find all related nodes with NodeID: " << funRetNodeID << " ====\n";
        
        std::set<NodeID> allRelatedNodes;
        
        std::cout << "\n==== First stage: traverse in edges ====\n";
        bool hasGepInInEdges = false;
        std::set<std::pair<std::string, std::string>> gepStructFieldSet; 
        std::queue<NodeID> inEdgeWorklist;
        std::set<NodeID> inEdgeVisited;
        
        inEdgeWorklist.push(funRetNodeID);
        inEdgeVisited.insert(funRetNodeID);
        allRelatedNodes.insert(funRetNodeID);
        
        while (!inEdgeWorklist.empty()) {
            NodeID curID = inEdgeWorklist.front();
            inEdgeWorklist.pop();
            
            const PAGNode* curNode = pag->getGNode(curID);
            if (!curNode) continue;
            
            std::cout << "\n--- Process in edge node " << curID << " ---\n";
            
            std::cout << "  In edge information:\n";
            bool hasValidInEdges = false;
            for (const PAGEdge* edge : curNode->getInEdges()) {
                NodeID srcID = edge->getSrcID();
                const PAGNode* srcNode = pag->getGNode(srcID);
                
                if (!srcNode) continue;
                
                if (srcNode->getFunction() != func) {
                    continue;
                }
                
                hasValidInEdges = true;
                std::string edgeTypeStr = getEdgeTypeStr(edge);                
                if (edge->getEdgeKind() == PAGEdge::Gep) {
                    hasGepInInEdges = true;
                    auto gepInfo = getGepStructInfo(edge);
                    gepStructFieldSet.insert(gepInfo);
                    std::cout << "      → Found GEP edge, set hasGepInInEdges = true\n";
                    std::cout << "      → GEP struct type: " << gepInfo.first << ", field: " << gepInfo.second << "\n";
                }
                                
                if (inEdgeVisited.find(srcID) == inEdgeVisited.end()) {
                    inEdgeVisited.insert(srcID);
                    allRelatedNodes.insert(srcID);
                    inEdgeWorklist.push(srcID);
                    std::cout << "      → Add to in edge traversal queue: " << srcID << "\n";
                }
            }
            
            if (!hasValidInEdges) {
                std::cout << "    No valid in edges\n";
            }
        }
        
        for (const auto& gepInfo : gepStructFieldSet) {
            std::cout << "  " << gepInfo.first << " -> " << gepInfo.second << "\n";
        }
        
        std::cout << "\n==== Second stage: traverse out edges ====\n";
        std::queue<NodeID> outEdgeWorklist;
        std::set<NodeID> outEdgeVisited;
        
        for (NodeID nodeId : allRelatedNodes) {
            outEdgeWorklist.push(nodeId);
            outEdgeVisited.insert(nodeId);
            std::cout << "Add first stage nodes to out edge traversal queue: " << nodeId << "\n";
        }
        
        while (!outEdgeWorklist.empty()) {
            NodeID curID = outEdgeWorklist.front();
            outEdgeWorklist.pop();
            
            const PAGNode* curNode = pag->getGNode(curID);
            if (!curNode) continue;
            
            std::cout << "\n--- Process out edge node " << curID << " ---\n";
            
            std::cout << "  Out edge information:\n";
            bool hasOutEdges = false;
            for (const PAGEdge* edge : curNode->getOutEdges()) {
                hasOutEdges = true;
                NodeID dstID = edge->getDstID();
                const PAGNode* dstNode = pag->getGNode(dstID);
                
                if (!dstNode) continue;
                
                if (dstNode->getFunction() != func) continue;
                
                std::string edgeTypeStr = getEdgeTypeStr(edge);
                std::cout << "    Out edge: " << curID << " --[" << edgeTypeStr << "]--> " << dstID 
                        << " (edge description: " << edge->toString() << ")\n";
                
                bool shouldStop = false;
                if (edge->getEdgeKind() == PAGEdge::Gep) {
                    if (hasGepInInEdges) {
                        auto currentGepInfo = getGepStructInfo(edge);
                        bool isSameStructField = gepStructFieldSet.find(currentGepInfo) != gepStructFieldSet.end();
                        
                        if (isSameStructField) {
                            std::cout << "      → Found GEP edge but access same struct field(" << currentGepInfo.first 
                                    << " -> " << currentGepInfo.second << "), continue traversal\n";
                        } else {
                            shouldStop = true;
                            std::cout << "      → Found GEP edge but access different struct field(" << currentGepInfo.first 
                                    << " -> " << currentGepInfo.second << "), stop traversal\n";
                        }
                    } else {
                        std::cout << "      → Found GEP edge but hasGepInInEdges=false, continue traversal\n";
                    }
                }
                
                if (!shouldStop && outEdgeVisited.find(dstID) == outEdgeVisited.end()) {
                    outEdgeVisited.insert(dstID);
                    allRelatedNodes.insert(dstID);
                    outEdgeWorklist.push(dstID);
                    std::cout << "      → Add to out edge traversal queue: " << dstID << "\n";
                } else if (shouldStop) {
                    std::cout << "      → Due to GEP stop strategy, not add to queue: " << dstID << "\n";
                } else {
                    std::cout << "      → Node already visited: " << dstID << "\n";
                }
            }
            
            std::cout << "  Check in edge information (additional traversal):\n";
            for (const PAGEdge* edge : curNode->getInEdges()) {
                NodeID srcID = edge->getSrcID();
                const PAGNode* srcNode = pag->getGNode(srcID);
                
                if (!srcNode) continue;
                
                if (srcNode->getFunction() != func) {
                    continue;
                }
                
                std::string edgeTypeStr = getEdgeTypeStr(edge);
                std::cout << "    In edge: " << srcID << " --[" << edgeTypeStr << "]--> " << curID 
                        << " (edge description: " << edge->toString() << ")\n";
                
                bool shouldStop = false;
                if (edge->getEdgeKind() == PAGEdge::Gep) {
                    if (hasGepInInEdges) {
                        auto currentGepInfo = getGepStructInfo(edge);
                        bool isSameStructField = gepStructFieldSet.find(currentGepInfo) != gepStructFieldSet.end();
                        
                        if (isSameStructField) {
                            std::cout << "      → Found GEP edge but access same struct field(" << currentGepInfo.first 
                                    << " -> " << currentGepInfo.second << "), continue traversal\n";
                        } else {
                            shouldStop = true;
                            std::cout << "      → Found GEP edge but access different struct field(" << currentGepInfo.first 
                                    << " -> " << currentGepInfo.second << "), stop traversal\n";
                        }
                    } else {
                        std::cout << "      → Found GEP edge but hasGepInInEdges=false, continue traversal\n";
                    }
                }
                
                if (!shouldStop && outEdgeVisited.find(srcID) == outEdgeVisited.end()) {
                    outEdgeVisited.insert(srcID);
                    allRelatedNodes.insert(srcID);
                    outEdgeWorklist.push(srcID);
                    std::cout << "      → Add to in edge traversal queue: " << srcID << "\n";
                } else if (shouldStop) {
                    std::cout << "      → Due to GEP stop strategy, not add to queue: " << srcID << "\n";
                } else {
                    std::cout << "      → Node already visited: " << srcID << "\n";
                }
            }
            
            if (!hasOutEdges) {
                std::cout << "    No out edges\n";
            }
        }
        
        std::cout << "\n==== Find all related nodes completed ====\n";
        std::cout << "Total found " << allRelatedNodes.size() << " related nodes:\n";
        for (NodeID id : allRelatedNodes) {
            const PAGNode* node = pag->getGNode(id);
            if (node) {
                std::cout << "  NodeID " << id << ": " << node->toString() << "\n";
            }
        }
        
        return allRelatedNodes;
    }

    bool isAllocationSource(const std::set<NodeID>& allRelatedNodes) {
        std::set<std::string> allocationFunctions = {
            "malloc", "calloc", "realloc", "aligned_alloc",
            "strdup", "strndup", 
            "g_malloc", "g_new", 
            "zmalloc"  
        };
                

        for (NodeID nodeID : allRelatedNodes) {
            const PAGNode* node = pag->getGNode(nodeID);            
            std::string nodeString = node->toString();            
            for (const std::string& allocFunc : allocationFunctions) {
                if (nodeString.find("@" + allocFunc) != std::string::npos) {
                    std::cout << "Found allocation function " << allocFunc << " in node: " << nodeString << std::endl;
                    return true;
                }
            }
        }
        return false;
    }

    std::string getFunctionCallFromInEdges(const std::set<NodeID>& allRelatedNodes) {
        std::vector<std::string> functionNames;        
        for (NodeID nodeID : allRelatedNodes) {
            const PAGNode* node = pag->getGNode(nodeID);
            
            std::string nodeStr = node->toString();
            std::cout << "Check node " << nodeID << ": " << nodeStr << std::endl;
            
            if (nodeStr.find(" = call ") != std::string::npos && nodeStr.find("@") != std::string::npos) {                
                size_t atPos = nodeStr.find("@");
                if (atPos != std::string::npos) {
                    size_t nameStart = atPos + 1; 
                    size_t nameEnd = nodeStr.find("(", nameStart);
                    if (nameEnd == std::string::npos) {
                        nameEnd = nodeStr.find(" ", nameStart);
                    }
                    
                    if (nameEnd != std::string::npos && nameEnd > nameStart) {
                        std::string functionName = nodeStr.substr(nameStart, nameEnd - nameStart);
                        if (std::find(functionNames.begin(), functionNames.end(), functionName) == functionNames.end()) {
                            functionNames.push_back(functionName);
                        }
                    }
                }
            }
        }
        
        if (functionNames.empty()) {
            return "";
        }
        
        std::string result = "OwnFrom ";
        for (size_t i = 0; i < functionNames.size(); ++i) {
            result += functionNames[i];
            if (i < functionNames.size() - 1) {
                result += ", ";
            }
        }
        
        std::cout << "Concatenation result: " << result << std::endl;
        return result;
    }
   

    std::string getLifeResult(const std::set<NodeID>& allRelatedNodes) {
        std::vector<std::string> parameterNames;
        
        std::cout << "Check " << allRelatedNodes.size() << " related nodes' life cycle dependency" << std::endl;
        
        for (NodeID nodeID : allRelatedNodes) {
            const PAGNode* node = pag->getGNode(nodeID);
            if (!node) continue;
            
            std::string nodeStr = node->toString();
            std::cout << "Check node " << nodeID << ": " << nodeStr << std::endl;
            
            if (nodeStr.find(" arg ") != std::string::npos) {
                std::string paramName = extractParameterName(nodeStr);
                if (!paramName.empty()) {
                    std::cout << "Extract parameter name from node " << nodeID << ": " << paramName << std::endl;
                    
                    if (std::find(parameterNames.begin(), parameterNames.end(), paramName) == parameterNames.end()) {
                        parameterNames.push_back(paramName);
                    }
                }
            }
        }
        
        if (parameterNames.empty()) {
            return "";
        } else if (parameterNames.size() == 1) {
            std::string result = "Return depends on `" + parameterNames[0] + "`";
            return result;
        } else {
            std::string result = "Return depends on `";
            for (size_t i = 0; i < parameterNames.size(); ++i) {
                result += parameterNames[i];
                if (i < parameterNames.size() - 1) {
                    result += ", ";
                }
            }
            return result;
        }
    }

    std::string extractParameterName(const std::string& nodeStr) {
        
        size_t percentPos = nodeStr.find("%");
        if (percentPos != std::string::npos) {
            size_t nameStart = percentPos + 1; 
            size_t nameEnd = nodeStr.find(" ", nameStart);
            if (nameEnd == std::string::npos) {
                nameEnd = nodeStr.find("{", nameStart);
            }
            
            if (nameEnd != std::string::npos && nameEnd > nameStart) {
                std::string paramName = nodeStr.substr(nameStart, nameEnd - nameStart);
                if (paramName != "retval" && paramName.find(".addr") == std::string::npos) {
                    return paramName;
                }
            }
        }
        
        return "";
    }


    void analyzeParam_pointTo(ContextDDA* pta, const SVFFunction* func) {        
        PTACallGraph* callgraph = pta->getPTACallGraph();
        bool hasPointerParam = false;
        std::map<NodeID, ParamPointsToInfo> paramPointsToMap;
        for (unsigned i = 0; i < func->arg_size(); i++) {
            const SVFArgument* arg = func->getArg(i);
            if (arg->getType()->isPointerTy()) {
                hasPointerParam = true;
                NodeID paramID = pag->getValueNode(arg);                    
                ParamPointsToInfo pointsToInfo;
                pointsToInfo.paramID = paramID;
                pointsToInfo.funcName = func->getName();
                pointsToInfo.paramName = arg->getName();
                paramPointsToMap[paramID] = pointsToInfo;
            }
        }
        
        if (!hasPointerParam) return;

        PTACallGraphNode* callGraphNode = callgraph->getCallGraphNode(func);
        if (!callGraphNode) return;

        for (PTACallGraphEdge* edge : callGraphNode->getInEdges()) {
            for (auto it = edge->getDirectCalls().begin(); it != edge->getDirectCalls().end(); ++it) {
                const CallICFGNode* callsite = *it;
                const SVFFunction* caller = callsite->getCaller();  
                
                int callerLineStart = -1;
                std::string callerFileName = "";
                const Value* llvmFunc = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(caller);
                if (const Function* F = dyn_cast<Function>(llvmFunc)) {
                    if (F->getSubprogram()) {
                        DISubprogram* SP = F->getSubprogram();
                        callerFileName = SP->getFilename().str();
                        callerLineStart = SP->getLine();
                    }
                }
                if (callerLineStart == -1) continue;
                for (auto& paramPair : paramPointsToMap) {
                    NodeID paramID = paramPair.first; 
                    ParamPointsToInfo& pointsToInfo = paramPair.second; 
                    NodeID actualArgID = 0; 
                    std::string callStmt = "";              
                    for (const SVFStmt* stmt : pag->getSVFStmtList(callsite)) {
                        if (const CallPE* callPE = SVFUtil::dyn_cast<CallPE>(stmt)) {
                            if (callPE->getLHSVarID() == paramID) { 
                                actualArgID = callPE->getRHSVarID(); 
                                callStmt = stmt->toString();
                                break;
                            }
                        }
                    }
                    
                    if (actualArgID == 0) continue;
                    auto [reversePaths, forwardPaths] = traceActualArgSource(actualArgID, callerLineStart);
                    
                    pointsToInfo.reversePaths[callsite] = reversePaths;
                    pointsToInfo.forwardPaths[callsite] = forwardPaths;

                    std::pair<std::string, std::string> pointInfo = getPointToInfo(reversePaths);
                    std::cout << "pointType: " << pointInfo.first<< "\n pointTo: " << pointInfo.second << std::endl;

                    pointsToInfo.pointsToInfo[callsite] = pointInfo;
                    std::string sameObject = isSameObject(actualArgID, caller, false);

                    pointsToInfo.callerInfo[callsite] = std::make_pair(actualArgID, sameObject);
                    pointsToInfo.callStmts[callsite] = callStmt;  
                    paramPointsToMap[paramID] = pointsToInfo;
                }
            }
        }
        funcParamPointsToMap[func] = paramPointsToMap;
    }


    std::pair<std::vector<std::vector<NodeID>>, std::vector<std::vector<NodeID>>> traceActualArgSource(NodeID nodeId, int callerLineStart) {
        const PAGNode* node = pag->getGNode(nodeId);
        if (!node) return {};
        
        std::map<NodeID, NodeInfo> reverseNodes;
        std::map<std::pair<NodeID, NodeID>, EdgeInfo> reverseEdges;
        std::map<NodeID, NodeID> reverseParent; 
        std::map<NodeID, std::string> reverseEdgeType; 
        std::map<NodeID, NodeInfo> forwardNodes;
        std::map<std::pair<NodeID, NodeID>, EdgeInfo> forwardEdges;
        std::map<NodeID, NodeID> forwardParent;
        std::map<NodeID, std::string> forwardEdgeType;
        
        std::map<NodeID, NodeInfo> allNodes;
        
        NodeInfo startNodeInfo = getNodeInfo(node);
        reverseNodes[nodeId] = startNodeInfo;
        forwardNodes[nodeId] = startNodeInfo;
        allNodes[nodeId] = startNodeInfo;
        int callsiteLine = startNodeInfo.line; 
        
        std::cout << "\n==== Start reverse traversal ====\n";
        
        std::set<NodeID> reverseVisited;
        std::queue<NodeID> reverseWorklist;
        
        reverseWorklist.push(nodeId);
        reverseVisited.insert(nodeId);
        
        while (!reverseWorklist.empty()) {
            NodeID curId = reverseWorklist.front();
            reverseWorklist.pop();
            
            const PAGNode* curNode = pag->getGNode(curId);
            if (!curNode) continue;
            
            for (const PAGEdge* edge : curNode->getInEdges()) {
                NodeID srcId = edge->getSrcID();
                std::string edgeTypeStr = getEdgeTypeStr(edge);
                
                const PAGNode* srcNode = pag->getGNode(srcId);
                if (!srcNode) continue;
                NodeInfo srcNodeInfo = getNodeInfo(srcNode);
                int srcNodeLine = srcNodeInfo.line;
                bool isStopTag = false;
                if (srcNodeLine < callerLineStart || srcNodeLine > callsiteLine){
                    isStopTag = true;
                    continue;
                }
                
                EdgeInfo edgeInfo;
                edgeInfo.srcId = srcId;
                edgeInfo.dstId = curId;
                edgeInfo.type = edgeTypeStr;
                edgeInfo.description = edge->toString();
                reverseEdges[{srcId, curId}] = edgeInfo;
                
                reverseNodes[srcId] = srcNodeInfo;
                allNodes[srcId] = srcNodeInfo;
                if (!isStopTag && reverseVisited.find(srcId) == reverseVisited.end()) {
                    reverseVisited.insert(srcId);
                    reverseWorklist.push(srcId);
                    reverseParent[srcId] = curId;
                    reverseEdgeType[srcId] = edgeTypeStr;
                }
            }
        }
        std::cout << "\n==== Reverse traversal completed ====\n";
        
        std::cout << "\n==== Start forward traversal ====\n";
        std::set<NodeID> reverseLeafNodes;
        for (const auto& nodePair : reverseNodes) {
            NodeID id = nodePair.first;
            bool hasInEdge = false;
            for (const auto& edgePair : reverseEdges) {
                if (edgePair.first.second == id) {
                    hasInEdge = true;
                    break;
                }
            }
            if (!hasInEdge && id != nodeId) { 
                reverseLeafNodes.insert(id);
            }
        }

        std::queue<NodeID> forwardWorklist;
        std::set<NodeID> forwardVisited;

        std::cout << "\n==== Build reverse path ====\n";
        std::map<NodeID, std::vector<std::pair<NodeID, std::string>>> reversePathGraph;
        for (const auto& edgePair : reverseEdges) {
            NodeID src = edgePair.first.first;
            NodeID dst = edgePair.first.second;
            std::string edgeStr = edgePair.second.type;
            reversePathGraph[dst].push_back({src, edgeStr});
        }
        
        std::vector<std::vector<NodeID>> reversePaths;
        std::vector<NodeID> currentReversePath;
        std::set<NodeID> onReversePath;
        std::function<void(NodeID)> reversePathDfs = [&](NodeID node) {
            currentReversePath.push_back(node);
            onReversePath.insert(node);
            
            if (reversePathGraph[node].empty()) {
                reversePaths.push_back(currentReversePath);
            } else {
                for (const auto& edge : reversePathGraph[node]) {
                    NodeID nextNode = edge.first;
                    if (onReversePath.find(nextNode) == onReversePath.end()) {
                        reversePathDfs(nextNode);
                    }
                }
            }
            
            currentReversePath.pop_back();
            onReversePath.erase(node);
        };
        reversePathDfs(nodeId);
        if (reversePaths.empty()) {
            std::vector<NodeID> singleNodePath = {nodeId};
            reversePaths.push_back(singleNodePath);
        }
        
        std::cout << "\n==== All reverse paths ====\n";
        for (size_t i = 0; i < reversePaths.size(); i++) {
            std::cout << "Reverse path" << (i+1) << ": ";
            const std::vector<NodeID>& path = reversePaths[i];
            for (size_t j = 0; j < path.size(); j++) {
                NodeID id = path[j];
                const NodeInfo& nodeInfo = reverseNodes[id];
                
                std::cout << id;
                
                if (!nodeInfo.file_name.empty() && nodeInfo.line > 0) {
                    std::cout << "[" << nodeInfo.file_name << ":" << nodeInfo.line << "]";
                }
                
                if (j < path.size() - 1) {
                    auto edgeIter = reverseEdges.find({path[j+1], path[j]});
                    std::string edgeStr = edgeIter != reverseEdges.end() ? edgeIter->second.type : "unknown";
                    std::cout << " <--[" << edgeStr << "]-- ";
                }
            }
            std::cout << "\n";
        }
        
        std::cout << "\n==== Build forward path ====\n";

        std::map<NodeID, std::vector<std::pair<NodeID, std::string>>> forwardPathGraph;
        for (const auto& edgePair : forwardEdges) {
            NodeID src = edgePair.first.first;
            NodeID dst = edgePair.first.second;
            std::string edgeStr = edgePair.second.type;
            forwardPathGraph[src].push_back({dst, edgeStr});
        }

        std::vector<std::vector<NodeID>> forwardPaths;
        std::vector<NodeID> currentForwardPath;
        std::set<NodeID> onForwardPath;

        std::set<NodeID> leafNodes;
        for (const auto& nodePair : forwardNodes) {
            NodeID id = nodePair.first;
            if (forwardPathGraph.find(id) == forwardPathGraph.end() || 
                forwardPathGraph[id].empty()) {
                leafNodes.insert(id);
            }
        }
        std::function<void(NodeID)> forwardPathDfs = [&](NodeID node) {
            currentForwardPath.push_back(node);
            onForwardPath.insert(node);
            if (leafNodes.find(node) != leafNodes.end() || 
                forwardPathGraph.find(node) == forwardPathGraph.end()) {
                if (currentForwardPath.size() > 1) {
                    forwardPaths.push_back(currentForwardPath);
                }
            } else {
                for (const auto& edge : forwardPathGraph[node]) {
                    NodeID nextNode = edge.first;
                    if (onForwardPath.find(nextNode) == onForwardPath.end()) {
                        forwardPathDfs(nextNode);
                    }
                }
            }
            currentForwardPath.pop_back();
            onForwardPath.erase(node);
        };
        for (NodeID topNode : reverseLeafNodes) {
            std::cout << "Build path from top node: " << topNode << "\n";
            currentForwardPath.clear();
            onForwardPath.clear();
            forwardPathDfs(topNode);
        }
        if (forwardPaths.empty() && reverseLeafNodes.find(nodeId) == reverseLeafNodes.end()) {
            std::cout << "Build path from original start node: " << nodeId << "\n";
            currentForwardPath.clear();
            onForwardPath.clear();
            forwardPathDfs(nodeId);
        }
        if (forwardPaths.empty()) {
            for (NodeID node : reverseLeafNodes) {
                std::vector<NodeID> singleNodePath = {node};
                forwardPaths.push_back(singleNodePath);
            }
            if (reverseLeafNodes.empty()) {
                std::vector<NodeID> singleNodePath = {nodeId};
                forwardPaths.push_back(singleNodePath);
            }
        }
        std::cout << "\n==== All forward paths ====\n";
        for (size_t i = 0; i < forwardPaths.size(); i++) {
            std::cout << "Forward path" << (i+1) << ": ";
            const std::vector<NodeID>& path = forwardPaths[i];
            for (size_t j = 0; j < path.size(); j++) {
                NodeID id = path[j];
                const NodeInfo& nodeInfo = forwardNodes[id];
                std::cout << id;
                if (!nodeInfo.file_name.empty() && nodeInfo.line > 0) {
                    std::cout << "[" << nodeInfo.file_name << ":" << nodeInfo.line << "]";
                }

                if (j < path.size() - 1) {
                    auto edgeIter = forwardEdges.find({path[j], path[j+1]});
                    std::string edgeStr = edgeIter != forwardEdges.end() ? edgeIter->second.type : "未知";
                    std::cout << " --[" << edgeStr << "]--> ";
                }
            }
            std::cout << "\n";
        }
    
        return std::make_pair(reversePaths, forwardPaths);
    }

    NodeInfo getNodeInfo(const PAGNode* node) {
        NodeInfo nodeInfo;
        if (!node) return nodeInfo;
        
        nodeInfo.id = node->getId();
        nodeInfo.type = getNodeTypeStr(node);
        nodeInfo.description = node->toString();
        nodeInfo.hasValue = node->hasValue();
        nodeInfo.file_name = "";
        nodeInfo.line = -1;


        std::string desc = node->toString();
        size_t lnPos = desc.find("\"ln\": ");
        size_t flPos = desc.find("\"fl\": ");
        size_t filePos = desc.find("\"file\": ");

        if (lnPos != std::string::npos) {
            lnPos += 6; 
            size_t commaPos = desc.find(",", lnPos);
            size_t bracePos = desc.find("}", lnPos);
            size_t endPos = std::min(commaPos != std::string::npos ? commaPos : desc.length(), 
                                    bracePos != std::string::npos ? bracePos : desc.length());
            
            nodeInfo.line = std::stoi(desc.substr(lnPos, endPos - lnPos));
        }
        
        if (flPos != std::string::npos) {
            flPos += 6; 
            if (flPos < desc.length() && desc[flPos] == '\"') {
                flPos++; 
                size_t endQuote = desc.find('\"', flPos);
                if (endQuote != std::string::npos) {
                    nodeInfo.file_name = desc.substr(flPos, endQuote - flPos);
                }
            }
        } else if (filePos != std::string::npos) {
            filePos += 8; 
            if (filePos < desc.length() && desc[filePos] == '\"') {
                filePos++; 
                size_t endQuote = desc.find('\"', filePos);
                if (endQuote != std::string::npos) {
                    nodeInfo.file_name = desc.substr(filePos, endQuote - filePos);
                }
            }
        }

        if (node->hasValue()) {
            const SVFValue* val = node->getValue();
            if (val) {
                try {
                    const Value* llvmVal = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(val);
                    if (llvmVal) {
                        nodeInfo.valueName = llvmVal->getName().str();
                        nodeInfo.valueType = getValueTypeStr(llvmVal);
                    }
                } catch (...) {
                    nodeInfo.valueName = "Error getting LLVM value";
                }
            }
        }
        
        return nodeInfo;
    }
    

    std::pair<std::string, std::string> getPointToInfo(const std::vector<std::vector<NodeID>>& reversePaths) {
        std::cout << "==== Start pointer analysis ====" << std::endl;

        std::string pointType = "unknown";
        std::string pointTo = "unknown";
        
        if (reversePaths.empty()) {
            return std::make_pair(pointType, pointTo);
        }
        
        for (const auto& path : reversePaths) {
            if (path.empty()) {
                continue;
            }
            
            NodeID targetNode = path.back();
            const PAGNode* node = pag->getGNode(targetNode);
            
            if (node->hasValue()) {
                const SVFValue* val = node->getValue();
                std::cout << "Analyze node: " << targetNode << ", value: " << val->toString() << "\n";
                               
                try {
                    const Value* llvmVal = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(val);
    
                    if (isa<Function>(llvmVal)) {
                        const Function* func = dyn_cast<Function>(llvmVal);
                        pointType = "function";
                        pointTo = func->getName().str();
                        return std::make_pair(pointType, pointTo);
                    }
                    
                    Type* type = llvmVal->getType();
                    
                    if (isa<AllocaInst>(llvmVal)) {
                        const AllocaInst* allocaInst = dyn_cast<AllocaInst>(llvmVal);
                        Type* allocatedType = allocaInst->getAllocatedType();
                        
                        if (allocatedType->isArrayTy()) {
                            pointType = "array";
                            ArrayType* arrayType = dyn_cast<ArrayType>(allocatedType);
                            Type* elemTypeOfArray = arrayType->getElementType();
                            unsigned size = arrayType->getNumElements();
                            
                            std::string elemTypeName = "unknown";
                            if (elemTypeOfArray->isIntegerTy()) {
                                elemTypeName = "i" + std::to_string(elemTypeOfArray->getIntegerBitWidth());
                            } else if (elemTypeOfArray->isFloatTy()) {
                                elemTypeName = "float";
                            } else if (elemTypeOfArray->isDoubleTy()) {
                                elemTypeName = "double";
                            } else if (elemTypeOfArray->isPointerTy()) {
                                Type* pointeeType = elemTypeOfArray->getPointerElementType();
                                if (pointeeType->isIntegerTy()) {
                                    elemTypeName = "i" + std::to_string(pointeeType->getIntegerBitWidth()) + "*";
                                } else if (pointeeType->isFloatTy()) {
                                    elemTypeName = "float*";
                                } else if (pointeeType->isDoubleTy()) {
                                    elemTypeName = "double*";
                                } else if (pointeeType->isStructTy() && dyn_cast<StructType>(pointeeType)->hasName()) {
                                    elemTypeName = dyn_cast<StructType>(pointeeType)->getName().str() + "*";
                                } else {
                                    elemTypeName = "pointer";
                                }
                            } else if (elemTypeOfArray->isStructTy()) {
                                StructType* structType = dyn_cast<StructType>(elemTypeOfArray);
                                if (structType->hasName()) {
                                    elemTypeName = structType->getName().str();
                                } else {
                                    elemTypeName = "struct";
                                }
                            } else {
                                elemTypeName = "complex";
                            }
                            std::string arrayName = allocaInst->getName().str();
                            pointTo = arrayName + ": [" + std::to_string(size) + " x " + elemTypeName + "]";
                            return std::make_pair(pointType, pointTo);
                        }
                        
                        if (allocatedType->isPointerTy()) {
                            Type* pointeeType = allocatedType->getPointerElementType();
                            
                            if (pointeeType->isStructTy()) {
                                StructType* structType = dyn_cast<StructType>(pointeeType);
                                if (structType->hasName()) {
                                    std::string typeName = structType->getName().str();
                                    
                                    if (typeName.find("struct.") == 0) {
                                        typeName = typeName.substr(7);
                                        pointType = "struct";
                                    } else if (typeName.find("union.") == 0) {
                                        typeName = typeName.substr(6);
                                        pointType = "union";
                                    } else {
                                        pointType = "struct";
                                    }
                                    
                                    pointTo = typeName;
                                    return std::make_pair(pointType, pointTo);
                                } else {
                                    pointType = "anonymous_struct";
                                    pointTo = "anonymous_struct_" + allocaInst->getName().str();
                                    return std::make_pair(pointType, pointTo);
                                }
                            }
                            else if (pointeeType->isFunctionTy()) {
                                pointType = "function_pointer";
                                FunctionType* funcType = dyn_cast<FunctionType>(pointeeType);
                                if (funcType) {
                                    unsigned numParams = funcType->getNumParams();
                                    pointTo = "function_with_" + std::to_string(numParams) + "_params";
                                }
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isArrayTy()) {
                                pointType = "array";
                                ArrayType* arrayType = dyn_cast<ArrayType>(pointeeType);
                                Type* elemTypeOfArray = arrayType->getElementType();
                                unsigned size = arrayType->getNumElements();
                                
                                std::string elemTypeName = "unknown";
                                if (elemTypeOfArray->isIntegerTy()) {
                                    elemTypeName = "int" + std::to_string(elemTypeOfArray->getIntegerBitWidth());
                                } else if (elemTypeOfArray->isFloatTy()) {
                                    elemTypeName = "float";
                                } else if (elemTypeOfArray->isDoubleTy()) {
                                    elemTypeName = "double";
                                } else {
                                    elemTypeName = "complex";
                                }
                                
                                pointTo = "array[" + std::to_string(size) + "]_of_" + elemTypeName;
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isIntegerTy()) {
                                pointType = "primitive_pointer";
                                unsigned bitWidth = pointeeType->getIntegerBitWidth();
                                pointTo = "i" + std::to_string(bitWidth) + "*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isFloatTy()) {
                                pointType = "primitive_pointer";
                                pointTo = "float*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isDoubleTy()) {
                                pointType = "primitive_pointer";
                                pointTo = "double*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isVoidTy()) {
                                pointType = "primitive_pointer";
                                pointTo = "void*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isPointerTy()) {
                                pointType = "pointer_to_pointer";
                                Type* deepPointeeType = pointeeType;
                                std::string pointerChain = "";
                                while (deepPointeeType->isPointerTy()) {
                                    pointerChain += "*";
                                    deepPointeeType = deepPointeeType->getPointerElementType();
                                }
                                
                                if (deepPointeeType->isIntegerTy()) {
                                    unsigned bitWidth = deepPointeeType->getIntegerBitWidth();
                                    pointTo = "i" + std::to_string(bitWidth) + pointerChain + "*";
                                }
                                else if (deepPointeeType->isFloatTy()) {
                                    pointTo = "float" + pointerChain + "*";
                                }
                                else if (deepPointeeType->isDoubleTy()) {
                                    pointTo = "double" + pointerChain + "*";
                                }
                                else if (deepPointeeType->isVoidTy()) {
                                    pointTo = "void" + pointerChain + "*";
                                }
                                else if (deepPointeeType->isStructTy()) {
                                    StructType* structType = dyn_cast<StructType>(deepPointeeType);
                                    if (structType->hasName()) {
                                        pointTo = structType->getName().str() + pointerChain + "*";
                                    } else {
                                        pointTo = "anonymous_struct" + pointerChain + "*";
                                    }
                                }
                                else {
                                    pointTo = "unknown_type" + pointerChain + "*";
                                }
                                return std::make_pair(pointType, pointTo);
                            }
                        }
                    }
                    else if (isa<LoadInst>(llvmVal)) {
                        const LoadInst* loadInst = dyn_cast<LoadInst>(llvmVal);
                        Type* loadedType = loadInst->getType();
                        
                        if (loadedType->isPointerTy()) {
                            Type* pointeeType = loadedType->getPointerElementType();
                            
                            if (pointeeType->isIntegerTy()) {
                                pointType = "primitive_pointer";
                                unsigned bitWidth = pointeeType->getIntegerBitWidth();
                                pointTo = "i" + std::to_string(bitWidth) + "*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isFloatTy()) {
                                pointType = "primitive_pointer";
                                pointTo = "float*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isDoubleTy()) {
                                pointType = "primitive_pointer";
                                pointTo = "double*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isVoidTy()) {
                                pointType = "primitive_pointer";
                                pointTo = "void*"; 
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (pointeeType->isStructTy()) {
                                StructType* structType = dyn_cast<StructType>(pointeeType);
                                if (structType->hasName()) {
                                    std::string typeName = structType->getName().str();
                                    
                                    if (typeName.find("struct.") == 0) {
                                        typeName = typeName.substr(7);
                                        pointType = "struct";
                                    } else if (typeName.find("union.") == 0) {
                                        typeName = typeName.substr(6);
                                        pointType = "union";
                                    } else {
                                        pointType = "struct";
                                    }
                                    
                                    pointTo = typeName + "*";
                                    return std::make_pair(pointType, pointTo);
                                }
                            }
                        }
                    }
                    
                    if (type && type->isPointerTy()) {
                        if (type->isOpaquePointerTy()) {
                            if (isa<BitCastInst>(llvmVal)) {
                                const BitCastInst* bitcastInst = dyn_cast<BitCastInst>(llvmVal);
                                Value* srcVal = bitcastInst->getOperand(0);
                                
                                if (isa<Function>(srcVal)) {
                                    const Function* func = dyn_cast<Function>(srcVal);
                                    pointType = "function";
                                    pointTo = func->getName().str();
                                    return std::make_pair(pointType, pointTo);
                                }
                                
                                Type* destType = bitcastInst->getDestTy();
                                if (destType->isPointerTy()) {
                                    Type* pointeeType = destType->getPointerElementType();
                                    
                                    if (pointeeType->isIntegerTy()) {
                                        pointType = "primitive_pointer";
                                        unsigned bitWidth = pointeeType->getIntegerBitWidth();
                                        pointTo = "i" + std::to_string(bitWidth) + "*";
                                        return std::make_pair(pointType, pointTo);
                                    }
                                    else if (pointeeType->isVoidTy()) {
                                        pointType = "primitive_pointer";
                                        pointTo = "i8*"; 
                                        return std::make_pair(pointType, pointTo);
                                    }
                                }
                                
                                pointType = "casted_pointer";
                                pointTo = bitcastInst->getName().str();
                                return std::make_pair(pointType, pointTo);
                            }
                            
                            pointType = "opaque_pointer";
                            pointTo = llvmVal->getName().str();
                            return std::make_pair(pointType, pointTo);
                        }

                        try {
                            Type* elemType = type->getPointerElementType();
                            if (elemType->isPointerTy()) {
                                Type* pointeeOfElemType = elemType->getPointerElementType();
                                if (pointeeOfElemType->isIntegerTy()) {
                                    pointType = "primitive_pointer";
                                    unsigned bitWidth = pointeeOfElemType->getIntegerBitWidth();
                                    pointTo = "i" + std::to_string(bitWidth) + "**";
                                    return std::make_pair(pointType, pointTo);
                                }
                                else if (pointeeOfElemType->isVoidTy()) {
                                    pointType = "primitive_pointer";
                                    pointTo = "void**"; 
                                    return std::make_pair(pointType, pointTo);
                                }
                                else if (pointeeOfElemType->isStructTy()) {
                                    StructType* structType = dyn_cast<StructType>(pointeeOfElemType);
                                    if (structType->hasName()) {
                                        std::string typeName = structType->getName().str();
                                        
                                        if (typeName.find("struct.") == 0) {
                                            typeName = typeName.substr(7);
                                            pointType = "struct_pointer_pointer";
                                        } else if (typeName.find("union.") == 0) {
                                            typeName = typeName.substr(6);
                                            pointType = "union_pointer_pointer";
                                        } else {
                                            pointType = "struct_pointer_pointer";
                                        }
                                        
                                        pointTo = typeName + "**";
                                        return std::make_pair(pointType, pointTo);
                                    }
                                }
                            }
                            if (elemType->isIntegerTy()) {
                                pointType = "primitive_pointer";
                                unsigned bitWidth = elemType->getIntegerBitWidth();
                                pointTo = "i" + std::to_string(bitWidth) + "*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (elemType->isFloatTy()) {
                                pointType = "primitive_pointer";
                                pointTo = "float*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (elemType->isDoubleTy()) {
                                pointType = "primitive_pointer";
                                pointTo = "double*";
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (elemType->isVoidTy()) {
                                pointType = "primitive_pointer";
                                pointTo = "void*"; // 或i8*
                                return std::make_pair(pointType, pointTo);
                            }
                            else if (elemType->isStructTy()) {
                                StructType* structType = dyn_cast<StructType>(elemType);
                                if (structType->hasName()) {
                                    std::string typeName = structType->getName().str();
                                    
                                    if (typeName.find("struct.") == 0) {
                                        typeName = typeName.substr(7);
                                        pointType = "struct_pointer";
                                    } else if (typeName.find("union.") == 0) {
                                        typeName = typeName.substr(6);
                                        pointType = "union_pointer";
                                    } else {
                                        pointType = "struct_pointer";
                                    }
                                    
                                    pointTo = typeName + "*";
                                    return std::make_pair(pointType, pointTo);
                                } else {
                                    pointType = "anonymous_struct_pointer";
                                    pointTo = "anonymous_struct*";
                                    return std::make_pair(pointType, pointTo);
                                }
                            }
                            else if (elemType->isFunctionTy()) {
                                pointType = "function_pointer";
                                FunctionType* funcType = dyn_cast<FunctionType>(elemType);
                                if (funcType) {
                                    unsigned numParams = funcType->getNumParams();
                                    pointTo = "function_with_" + std::to_string(numParams) + "_params";
                                } else {
                                    pointTo = "unknown_function";
                                }
                                return std::make_pair(pointType, pointTo);
                            }
                        } catch (...) {
                            pointType = "unknown_pointer";
                            pointTo = llvmVal->getName().str();
                            return std::make_pair(pointType, pointTo);
                        }
                    }
                    
                    if (type->isIntegerTy()) {
                        pointType = "primitive";
                        unsigned bitWidth = type->getIntegerBitWidth();
                        pointTo = "i" + std::to_string(bitWidth);
                        return std::make_pair(pointType, pointTo);
                    }
                    else if (type->isFloatTy()) {
                        pointType = "primitive";
                        pointTo = "float";
                        return std::make_pair(pointType, pointTo);
                    }
                    else if (type->isDoubleTy()) {
                        pointType = "primitive";
                        pointTo = "double";
                        return std::make_pair(pointType, pointTo);
                    }
                    else if (type->isVoidTy()) {
                        pointType = "primitive";
                        pointTo = "void";
                        return std::make_pair(pointType, pointTo);
                    }
                    else if (type->isStructTy()) {
                        StructType* structType = dyn_cast<StructType>(type);
                        if (structType->hasName()) {
                            std::string typeName = structType->getName().str();
                            
                            if (typeName.find("struct.") == 0) {
                                typeName = typeName.substr(7);
                                pointType = "struct_value";
                            } else if (typeName.find("union.") == 0) {
                                typeName = typeName.substr(6);
                                pointType = "union_value";
                            } else {
                                pointType = "struct_value";
                            }
                            
                            pointTo = typeName;
                            return std::make_pair(pointType, pointTo);
                        } else {
                            pointType = "anonymous_struct_value";
                            pointTo = "anonymous_struct";
                            return std::make_pair(pointType, pointTo);
                        }
                    }
                    
                } catch (...) {
                    continue;
                }
            } else {
                if (node->getNodeKind() == PAGNode::DummyObjNode ||
                    node->getNodeKind() == PAGNode::DummyValNode) {
                    pointType = "dummy_node";
                    pointTo = "dummy_" + std::to_string(targetNode);
                }
                else if (node->getNodeKind() == PAGNode::GepObjNode) {
                    pointType = "gep_object";
                    pointTo = "field_of_struct_" + std::to_string(targetNode);
                }
                else {
                    pointType = "special_node";
                    pointTo = "node_type_" + std::to_string(node->getNodeKind()) + "_id_" + std::to_string(targetNode);
                }
                
                if (pointType != "unknown" && pointTo != "unknown") {
                    return std::make_pair(pointType, pointTo);
                }
            }
        }
        std::cout << "==== Pointer analysis completed ====" << std::endl;
        return std::make_pair(pointType, pointTo);
    }
    
    std::string getNodeTypeStr(const PAGNode* node) {
        if (!node) return "NULL";
        
        switch (node->getNodeKind()) {
            case PAGNode::ValNode:     return "ValNode";
            case PAGNode::ObjNode:     return "ObjNode";
            case PAGNode::RetNode:     return "RetNode";
            case PAGNode::VarargNode:  return "VarargNode";
            case PAGNode::GepValNode:  return "GepValNode";
            case PAGNode::GepObjNode:  return "GepObjNode";
            case PAGNode::FIObjNode:   return "FIObjNode";
            case PAGNode::DummyValNode:return "DummyValNode";
            case PAGNode::DummyObjNode:return "DummyObjNode";
            default:                   return "Unknown";
        }
    }

    std::string getEdgeTypeStr(const PAGEdge* edge) {
        if (!edge) return "NULL";
        
        switch (edge->getEdgeKind()) {
            case PAGEdge::Addr:      return "Addr";
            case PAGEdge::Copy:      return "Copy";
            case PAGEdge::Store:     return "Store";
            case PAGEdge::Load:      return "Load";
            case PAGEdge::Call:      return "Call";
            case PAGEdge::Ret:       return "Ret";
            case PAGEdge::Gep:       return "Gep";
            case PAGEdge::ThreadFork:return "ThreadFork";
            case PAGEdge::ThreadJoin:return "ThreadJoin";
            default:                 return "Unknown";
        }
    }

    std::string getValueTypeStr(const Value* val) {
        if (!val) return "NULL";
        
        Type* type = val->getType();
        std::string typeStr = "";
        
        if (isa<Instruction>(val)) {
            typeStr += "Instruction(";
            if (isa<AllocaInst>(val)) typeStr += "Alloca";
            else if (isa<LoadInst>(val)) typeStr += "Load";
            else if (isa<StoreInst>(val)) typeStr += "Store";
            else if (isa<GetElementPtrInst>(val)) typeStr += "GEP";
            else if (isa<CallInst>(val)) typeStr += "Call";
            else if (isa<BitCastInst>(val)) typeStr += "BitCast";
            else typeStr += "Other";
            typeStr += ")";
        }
        else if (isa<Argument>(val)) typeStr += "Argument";
        else if (isa<Function>(val)) typeStr += "Function";
        else if (isa<GlobalVariable>(val)) typeStr += "GlobalVariable";
        else if (isa<Constant>(val)) {
            typeStr += "Constant";
            if (isa<ConstantPointerNull>(val)) typeStr += "(Null)";
        }
        else typeStr += "OtherValue";
        
        typeStr += ":";
        
        if (!type) {
            typeStr += "Unknown";
            return typeStr;
        }
        
        if (type->isPointerTy()) {
            typeStr += "Pointer";
            
            if (type->isOpaquePointerTy()) {
                typeStr += "(Opaque)";
                return typeStr;
            }
            
            Type* elemTy = nullptr;
            try {
                if (type->getNumContainedTypes() > 0) {
                    elemTy = type->getPointerElementType();
                }
            } catch (...) {
                typeStr += "(Unknown)";
                return typeStr;
            }
            
            if (!elemTy) {
                typeStr += "(Unknown)";
                return typeStr;
            }
            
            typeStr += "(";
            
            if (elemTy->isFunctionTy()) typeStr += "Function";
            else if (elemTy->isStructTy()) {
                StructType* structTy = dyn_cast<StructType>(elemTy);
                typeStr += "Struct";
                if (structTy && structTy->hasName()) typeStr += "(" + structTy->getName().str() + ")";
            }
            else if (elemTy->isArrayTy()) typeStr += "Array";
            else if (elemTy->isIntegerTy()) typeStr += "Int" + std::to_string(elemTy->getIntegerBitWidth());
            else if (elemTy->isFloatTy()) typeStr += "Float";
            else if (elemTy->isDoubleTy()) typeStr += "Double";
            else if (elemTy->isVoidTy()) typeStr += "Void";
            else if (elemTy->isPointerTy()) typeStr += "PointerToPointer";
            else typeStr += "Other";
            
            typeStr += ")";
        }
        else {
            if (type->isIntegerTy()) typeStr += "Int" + std::to_string(type->getIntegerBitWidth());
            else if (type->isFloatTy()) typeStr += "Float";
            else if (type->isDoubleTy()) typeStr += "Double";
            else if (type->isVoidTy()) typeStr += "Void";
            else if (type->isFunctionTy()) typeStr += "Function";
            else typeStr += "Other";
        }
        
        return typeStr;
    }


    void analyzeStructMemberUsage(ContextDDA* pta, const SVFFunction* func) {
        std::cout << "Analyzing struct member usage for function " << func->getName() << std::endl;
        if (funcParamPointsToMap.find(func) == funcParamPointsToMap.end()) return;

        std::map<NodeID, ParamPointsToInfo>& paramPointsToMap = funcParamPointsToMap[func];
        
        if (paramPointsToMap.empty()) return;

        for (auto& paramPair : paramPointsToMap) {
            NodeID paramID = paramPair.first;
            ParamPointsToInfo& pointsToInfo = paramPair.second;
            
            const PAGNode* paramNode = pag->getGNode(paramID);
            if (!paramNode || !paramNode->hasValue()) continue;
            
            const SVFValue* svfVal = paramNode->getValue();
            if (!svfVal) continue;
            
            const Value* llvmVal = LLVMModuleSet::getLLVMModuleSet()->getLLVMValue(svfVal);
            if (!llvmVal) continue;
            
            Type* type = llvmVal->getType();
            if (!type || !type->isPointerTy()) continue;
            
            Type* pointeeType = nullptr;
            try {
                pointeeType = type->getPointerElementType();
            } catch (...) {
                continue;
            }
            
            bool isStructPointer = false;
            std::string structTypeName = "";
            
            if (pointeeType->isStructTy()) {
                isStructPointer = true;
                StructType* structType = dyn_cast<StructType>(pointeeType);
                if (structType && structType->hasName()) {
                    structTypeName = structType->getName().str();
                    if (structTypeName.find("struct.") == 0) {
                        structTypeName = structTypeName.substr(7);
                    }
                } else {
                    structTypeName = "anonymous_struct";
                }
            }
            
            if (!isStructPointer) continue;
            
            std::cout << "Analyzing struct member usage for parameter " << pointsToInfo.paramName 
                    << " (ID: " << paramID << ") of type " << structTypeName << " in function " 
                    << func->getName() << std::endl;
            
            std::map<int, std::string> fieldAccesses; 
            std::set<NodeID> visited;
            std::queue<NodeID> worklist;
            
            worklist.push(paramID);
            visited.insert(paramID);
            
            while (!worklist.empty()) {
                NodeID curID = worklist.front();
                worklist.pop();
                
                const PAGNode* curNode = pag->getGNode(curID);
                if (!curNode) continue;
                
                if (curNode->getFunction() != func) {
                    continue;
                }
                
                for (const PAGEdge* edge : curNode->getOutEdges()) {
                    NodeID dstID = edge->getDstID();
                    const PAGNode* dstNode = pag->getGNode(dstID);
                    if (!dstNode || dstNode->getFunction() != func) {
                        continue;
                    }
                    
                    if (edge->getEdgeKind() == PAGEdge::Gep) {
                        const GepStmt* gepStmt = SVFUtil::dyn_cast<GepStmt>(edge);
                        if (!gepStmt) continue;
                        
                        const AccessPath& ap = gepStmt->getAccessPath();
                        if (ap.isConstantOffset()) {
                            int fieldIdx = ap.getConstantStructFldIdx();
                            std::string fieldDesc = "field_" + std::to_string(fieldIdx);
                            
                            if (pointeeType->isStructTy()) {
                                StructType* structType = dyn_cast<StructType>(pointeeType);
                            }
                            
                            fieldAccesses[fieldIdx] = fieldDesc;
                        } else {
                            fieldAccesses[-1] = "variant_index";
                        }
                    }
                    
                    if (visited.find(dstID) == visited.end()) {
                        visited.insert(dstID);
                        worklist.push(dstID);
                    }
                }
                
                for (const PAGEdge* edge : curNode->getInEdges()) {
                    NodeID srcID = edge->getSrcID();
                    const PAGNode* srcNode = pag->getGNode(srcID);
                    if (!srcNode || srcNode->getFunction() != func) {
                        continue;
                    }
                    
                    if (edge->getEdgeKind() == PAGEdge::Gep) {
                        const GepStmt* gepStmt = SVFUtil::dyn_cast<GepStmt>(edge);
                        if (!gepStmt) continue;
                        
                        const AccessPath& ap = gepStmt->getAccessPath();
                        if (ap.isConstantOffset()) {
                            int fieldIdx = ap.getConstantStructFldIdx();
                            std::string fieldDesc = "field_" + std::to_string(fieldIdx);
                            fieldAccesses[fieldIdx] = fieldDesc;
                        } else {
                            fieldAccesses[-1] = "variant_index";
                        }
                    }
                    
                    if (visited.find(srcID) == visited.end()) {
                        visited.insert(srcID);
                        worklist.push(srcID);
                    }
                }
            }
            
            std::cout << "Checking if parameter " << pointsToInfo.paramName << " is passed to other functions..." << std::endl;
            
            PTACallGraph* callgraph = pta->getPTACallGraph();
            ICFG* icfg = pag->getICFG();
            
            for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
                ICFGNode* node = it->second;
                if (node->getFun() != func) continue; 
                
                if (CallICFGNode* callsite = SVFUtil::dyn_cast<CallICFGNode>(node)) {
                    const SVFInstruction* callInst = callsite->getCallSite();
                    const SVFFunction* callee = SVFUtil::getCallee(callInst);
                    
                    if (SVFUtil::isIntrinsicInst(callInst)) continue;
                    
                    NodeID formalArgID = -1;
                    for (const SVFStmt* stmt : pag->getSVFStmtList(callsite)) {
                        if (const CallPE* callPE = SVFUtil::dyn_cast<CallPE>(stmt)) {
                            NodeID actualArgID = callPE->getRHSVarID(); 
                            
                            std::string _sameObject = isSameObject(actualArgID, func, true);
                            if (_sameObject != "not_caller_param") {
                                size_t colonPos = _sameObject.find(':');
                                if (colonPos != std::string::npos) {
                                    std::string extractedName = _sameObject.substr(0, colonPos);
                                    
                                    const SVFValue* val = paramNode->getValue();
                                    std::string currentParamName = val->getName();
                                    if (extractedName == currentParamName) {
                                        formalArgID = callPE->getLHSVarID();
                                        std::cout << "Parameter " << currentParamName << " is passed to function " 
                                                << callee->getName() << " as formal parameter ID " << formalArgID << std::endl;
                                        break;
                                    }
                                }
                            }
                        }
                    }
                    
                    if (formalArgID != -1) {
                        if (callee && !callee->isDeclaration() && funcParamPointsToMap.find(callee) != funcParamPointsToMap.end()) {
                            const std::map<NodeID, ParamPointsToInfo>& calleeParamInfo = funcParamPointsToMap[callee];
                            
                            auto calleeParamIt = calleeParamInfo.find(formalArgID);
                            if (calleeParamIt != calleeParamInfo.end()) {
                                const ParamPointsToInfo& calleeParamData = calleeParamIt->second;
                                
                                std::string calleeMemberUsage = calleeParamData.structMemberUsage;
                                std::cout << "Found struct member usage in callee: " << calleeMemberUsage << std::endl;
                                
                                if (calleeMemberUsage != "No struct members accessed") {
                                    size_t startPos = calleeMemberUsage.find("{");
                                    size_t endPos = calleeMemberUsage.find("}");
                                    
                                    if (startPos != std::string::npos && endPos != std::string::npos) {
                                        std::string fieldsStr = calleeMemberUsage.substr(startPos + 1, endPos - startPos - 1);
                                        
                                        std::vector<std::string> fields;
                                        size_t pos = 0;
                                        while ((pos = fieldsStr.find(",", pos)) != std::string::npos) {
                                            std::string field = fieldsStr.substr(0, pos);
                                            field.erase(0, field.find_first_not_of(" "));
                                            field.erase(field.find_last_not_of(" ") + 1);
                                            fields.push_back(field);
                                            fieldsStr = fieldsStr.substr(pos + 1);
                                            pos = 0;
                                        }
                                        if (!fieldsStr.empty()) {
                                            fieldsStr.erase(0, fieldsStr.find_first_not_of(" "));
                                            fieldsStr.erase(fieldsStr.find_last_not_of(" ") + 1);
                                            fields.push_back(fieldsStr);
                                        }
                                        
                                        for (const std::string& field : fields) {
                                            if (field == "variant_index") {
                                                fieldAccesses[-1] = "variant_index";
                                            } else if (field.find("field_") == 0) {
                                                int fieldIdx = std::stoi(field.substr(6));
                                                fieldAccesses[fieldIdx] = field;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            std::string memberUsage = "";
            if (!fieldAccesses.empty()) {
                memberUsage = structTypeName + ": {";
                bool first = true;
                for (const auto& fieldPair : fieldAccesses) {
                    if (!first) memberUsage += ", ";
                    if (fieldPair.first == -1) {
                        memberUsage += "variant_index";
                    } else {
                        memberUsage += fieldPair.second;
                    }
                    first = false;
                }
                memberUsage += "}";
            } else {
                memberUsage = "No struct members accessed";
            }
            
            pointsToInfo.structMemberUsage = memberUsage;
            std::cout << "Struct member usage for parameter " << pointsToInfo.paramName << ": " << memberUsage << std::endl;
        }
    }

    void analyzeParam_Mutability_Nullability(ContextDDA* pta, const SVFFunction* func) {        
        if (funcParamPointsToMap.find(func) == funcParamPointsToMap.end()) {
            std::cout << "Warning: No points-to information available for function " << func->getName() 
                    << ". Skipping mutability and nullability analysis." << std::endl;
            return;
        }

        std::map<NodeID, ParamPointsToInfo>& paramPointsToMap = funcParamPointsToMap[func];
        if (paramPointsToMap.empty()) return;
        for (auto& paramPair : paramPointsToMap) {
            NodeID paramID = paramPair.first;
            ParamPointsToInfo& pointsToInfo = paramPair.second;
        
            bool isModified = hasInternalModification(paramID, func);
            bool isNullable = hasInternalNullAssignmentOrCheck(paramID, func);

            if (!isModified || !isNullable) {
                PTACallGraph* callgraph = pta->getPTACallGraph();
                ICFG* icfg = pag->getICFG();
                for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
                    ICFGNode* node = it->second;
                    if (node->getFun() != func) continue;
                    if (CallICFGNode* callsite = SVFUtil::dyn_cast<CallICFGNode>(node)) {
                        const SVFInstruction* callInst = callsite->getCallSite();
                        const SVFFunction* callee = SVFUtil::getCallee(callInst);
                        std::cout << "callInst: " << callInst->toString() << std::endl;
                        if (SVFUtil::isIntrinsicInst(callInst)) continue;
                        // funcA(a, b): ... call funcB(a',b')
                        NodeID formalArgID = -1;
                        for (const SVFStmt* stmt : pag->getSVFStmtList(callsite)) {
                            std::cout << "stmt: " << stmt->toString() << std::endl;
                            
                            if (const CallPE* callPE = SVFUtil::dyn_cast<CallPE>(stmt)) {
                                NodeID actualArgID = callPE->getRHSVarID(); 
                                std::string _sameObject = isSameObject(actualArgID, func, false);
                                if (_sameObject != "not_caller_param"){
                                    size_t colonPos = _sameObject.find(':');
                                    if(colonPos != std::string::npos){
                                        std::string idStr = _sameObject.substr(colonPos + 1);
                                        NodeID sameObjectParamID = std::stoi(idStr);
                                        if (sameObjectParamID == paramID){
                                            formalArgID = callPE->getLHSVarID(); // 形参ID
                                            break;
                                        }
                                    }
                                }
                            }
                        }

                        if (formalArgID != -1) {
                            if (callee && !callee->isDeclaration() && funcParamPointsToMap.find(callee) != funcParamPointsToMap.end()) {
                                const std::map<NodeID, ParamPointsToInfo>& calleeParamInfo = funcParamPointsToMap[callee];
                                
                                auto calleeParamIt = calleeParamInfo.find(formalArgID);
                                if (calleeParamIt != calleeParamInfo.end()) {
                                    const ParamPointsToInfo& calleeParamData = calleeParamIt->second;
                                    
                                    if (!isModified && calleeParamData.mutabilityResult == "Mutable") {
                                        isModified = true;
                                    }

                                    if (!isNullable && calleeParamData.nullabilityResult == "Nullable") {
                                        isNullable = true;
                                    }
                                }
                            }
                        }

                    }
                }
            }

            pointsToInfo.mutabilityResult = isModified ? "Mutable" : "Immutable";
            pointsToInfo.nullabilityResult = isNullable ? "Nullable" : "Not_nullable";
        }

    }

    bool hasInternalModification(NodeID param, const SVFFunction* func) {

        const PAGNode* paramNode = pag->getGNode(param);
        if (!paramNode) return false;
        
        if (!paramNode->getType()->isPointerTy()) 
            return false;
        
        std::set<NodeID> paramStorage;
        std::set<NodeID> loadedValues;
        std::set<NodeID> gepFromParam;
        std::set<NodeID> visited;
        
        ICFG* icfg = pag->getICFG();
        
        for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
            ICFGNode* node = it->second;
            if (node->getFun() != func) continue;

            for (const SVFStmt* stmt : pag->getSVFStmtList(node)) {
                if (const StoreStmt* store = SVFUtil::dyn_cast<StoreStmt>(stmt)) {
                    if (store->getRHSVarID() == param) {
                        paramStorage.insert(store->getLHSVarID());
                    }
                }
                else if (const GepStmt* gep = SVFUtil::dyn_cast<GepStmt>(stmt)) {
                    if (gep->getRHSVarID() == param) {
                        gepFromParam.insert(gep->getLHSVarID());
                    }
                    else if (!paramStorage.empty() && loadedValues.count(gep->getRHSVarID())) {
                        gepFromParam.insert(gep->getLHSVarID());
                    }
                }
                else if (const LoadStmt* load = SVFUtil::dyn_cast<LoadStmt>(stmt)) {
                    if (paramStorage.count(load->getRHSVarID())) {
                        loadedValues.insert(load->getLHSVarID());
                    }
                    else if (load->getRHSVarID() == param) {
                        loadedValues.insert(load->getLHSVarID());
                    }
                }
            }
        }
        
        if (paramStorage.empty() && gepFromParam.empty()) {
            for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
                ICFGNode* node = it->second;
                if (node->getFun() != func) continue;
                
                for (const SVFStmt* stmt : pag->getSVFStmtList(node)) {
                    if (const StoreStmt* store = SVFUtil::dyn_cast<StoreStmt>(stmt)) {
                        if (store->getLHSVarID() == param) {
                            return true;
                        }
                    }
                }
            }
            return checkPointeeModified(param, func);
        }
        
        std::set<NodeID> valuesToTrack = loadedValues;
        std::set<NodeID> gepValuesToTrack = gepFromParam;
        
        for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
            ICFGNode* node = it->second;
            if (node->getFun() != func) continue;
            
            for (const SVFStmt* stmt : pag->getSVFStmtList(node)) {
                if (const LoadStmt* load = SVFUtil::dyn_cast<LoadStmt>(stmt)) {
                    if (paramStorage.count(load->getRHSVarID()) || gepFromParam.count(load->getRHSVarID())) {
                        valuesToTrack.insert(load->getLHSVarID());
                    }
                }
                else if (const GepStmt* gep = SVFUtil::dyn_cast<GepStmt>(stmt)) {
                    if (valuesToTrack.count(gep->getRHSVarID())) {
                        gepValuesToTrack.insert(gep->getLHSVarID());
                    }
                }
            }
        }
        
        for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
            ICFGNode* node = it->second;
            if (node->getFun() != func) continue;
            
            for (const SVFStmt* stmt : pag->getSVFStmtList(node)) {
                if (const StoreStmt* store = SVFUtil::dyn_cast<StoreStmt>(stmt)) {
                    NodeID lhs = store->getLHSVarID();
                    
                    if (valuesToTrack.count(lhs)) {
                        return true; 
                    }
                    
                    if (gepValuesToTrack.count(lhs)) {
                        return true; 
                    }
                    
                    if (lhs == param) {
                        return true;
                    }
                }
            }
        }
        
        return false;
    }

    bool checkPointeeModified(NodeID param, const SVFFunction* func) {
        std::set<NodeID> relatedNodes;
        std::set<NodeID> visited;
        std::queue<NodeID> worklist;
        
        worklist.push(param);
        visited.insert(param);
        
        while (!worklist.empty()) {
            NodeID curID = worklist.front();
            worklist.pop();
            relatedNodes.insert(curID);
            
            const PAGNode* curNode = pag->getGNode(curID);
            if (!curNode) continue;
            
            for (const PAGEdge* edge : curNode->getOutEdges()) {
                NodeID dstID = edge->getDstID();
                if (visited.find(dstID) == visited.end()) {
                    worklist.push(dstID);
                    visited.insert(dstID);
                }
            }
            
            for (const PAGEdge* edge : curNode->getInEdges()) {
                NodeID srcID = edge->getSrcID();
                if (visited.find(srcID) == visited.end()) {
                    worklist.push(srcID);
                    visited.insert(srcID);
                }
            }
        }
        
        ICFG* icfg = pag->getICFG();
        for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
            ICFGNode* node = it->second;
            if (node->getFun() != func) continue;
            
            for (const SVFStmt* stmt : pag->getSVFStmtList(node)) {
                if (const StoreStmt* store = SVFUtil::dyn_cast<StoreStmt>(stmt)) {
                    NodeID lhsID = store->getLHSVarID();
                    NodeID rhsID = store->getRHSVarID();
                    
                    if (relatedNodes.count(lhsID)) {
                        const PAGNode* lhsNode = pag->getGNode(lhsID);
                        const PAGNode* rhsNode = pag->getGNode(rhsID);
                        
                        bool isStoringToAddress = false;
                        if (lhsNode && rhsNode) {
                            if (lhsNode->getType() && lhsNode->getType()->isPointerTy()) {
                                if (rhsID == param || relatedNodes.count(rhsID)) {
                                    isStoringToAddress = true;
                                }
                            }
                        }
                        
                        if (!isStoringToAddress) {
                            return true;  
                        } else {
                            std::cout << "Skipping StoreStmt in checkPointeeModified (storing to address): " 
                                      << store->toString() << std::endl;
                        }
                    }
                }
            }
        }
        
        return false;
    }

    bool hasInternalNullAssignmentOrCheck(NodeID param, const SVFFunction* func) {
        const PAGNode* paramNode = pag->getGNode(param);
        if (!paramNode) return false;
        
        ICFG* icfg = pag->getICFG();
        for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
            ICFGNode* node = it->second;
            if (node->getFun() != func) continue;
            for (const SVFStmt* stmt : pag->getSVFStmtList(node)) {
                if (const CmpStmt* cmp = SVFUtil::dyn_cast<CmpStmt>(stmt)) {
                    for (u32_t i = 0; i < cmp->getOpVarNum(); i++) {
                        NodeID opId = cmp->getOpVarID(i);
                        if (opId == param) {
                            for (u32_t j = 0; j < cmp->getOpVarNum(); j++) {
                                if (j != i) {
                                    NodeID otherOpId = cmp->getOpVarID(j);
                                    if (pag->isNullPtr(otherOpId)) {
                                        return true; 
                                    }
                                }
                            }
                        }
                    }
                }
                else if (const CopyStmt* copy = SVFUtil::dyn_cast<CopyStmt>(stmt)) {
                    if (copy->getLHSVarID() == param && pag->isNullPtr(copy->getRHSVarID())) {
                        return true; 
                    }
                }
                else if (const StoreStmt* store = SVFUtil::dyn_cast<StoreStmt>(stmt)) {
                    if (pag->isNullPtr(store->getRHSVarID())) {
                        NodeID dstId = store->getLHSVarID();
                        
                        PointsTo pts;
                        if (getPointsToFromParam(param, pts)) {
                            if (pts.test(dstId)) {
                                return true; 
                            }
                        }
                        
                        std::set<NodeID> visited;
                        std::queue<NodeID> worklist;
                        worklist.push(dstId);
                        visited.insert(dstId);
                        
                        bool foundConnection = false;
                        while (!worklist.empty() && !foundConnection) {
                            NodeID curId = worklist.front();
                            worklist.pop();
                            
                            const PAGNode* curNode = pag->getGNode(curId);
                            if (!curNode) continue;
                            
                            for (const PAGEdge* edge : curNode->getInEdges()) {
                                NodeID srcId = edge->getSrcID();
                                
                                if (srcId == param || 
                                    (edge->getEdgeKind() == PAGEdge::Load && 
                                    edge->getSrcID() == param)) {
                                    foundConnection = true;
                                    break;
                                }
                                
                                if (visited.find(srcId) == visited.end()) {
                                    worklist.push(srcId);
                                    visited.insert(srcId);
                                }
                            }
                        }
                        
                        if (foundConnection) {
                            return true;
                        }
                    }
                }
                
                if (const BranchStmt* branch = SVFUtil::dyn_cast<BranchStmt>(stmt)) {
                    const SVFVar* condVar = branch->getCondition();
                    if (condVar) {
                        const SVFValue* condValue = condVar->getValue();
                        if (condValue && pag->hasValueNode(condValue)) {
                            NodeID condID = pag->getValueNode(condValue);
                            const PAGNode* condNode = pag->getGNode(condID);
                            
                            if (condNode) {
                                std::set<NodeID> visited;
                                std::queue<NodeID> worklist;
                                worklist.push(condID);
                                visited.insert(condID);
                                
                                while (!worklist.empty()) {
                                    NodeID curID = worklist.front();
                                    worklist.pop();
                                    
                                    if (curID == param) {
                                        return true;
                                    }
                                    
                                    const PAGNode* curNode = pag->getGNode(curID);
                                    if (!curNode) continue;
                                    
                                    for (const PAGEdge* edge : curNode->getInEdges()) {
                                        NodeID srcID = edge->getSrcID();
                                        if (visited.find(srcID) == visited.end()) {
                                            worklist.push(srcID);
                                            visited.insert(srcID);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        return false;
    }

    bool getPointsToFromParam(NodeID param, PointsTo& pts) {
        const PAGNode* paramNode = pag->getGNode(param);
        if (!paramNode) return false;
        
        bool pointsToFound = false;
        if (const SVFVar* svfVar = SVFUtil::dyn_cast<SVFVar>(paramNode)) {
            if (pag->hasValueNode(svfVar->getValue())) {
                NodeID valNodeId = pag->getValueNode(svfVar->getValue());
                const PAGNode* valNode = pag->getGNode(valNodeId);
                if (valNode) {
                    for (const auto& edge : valNode->getOutEdges()) {
                        if (edge->getEdgeKind() == PAGEdge::Addr) {
                            NodeID pointeeId = edge->getDstID();
                            pts.set(pointeeId);
                            pointsToFound = true;
                        }
                    }
                }
            }
        }
        
        return pointsToFound;
    }
    

    void analyzeParam_Ownership(ContextDDA* pta, const SVFFunction* func) {
        std::map<NodeID, ParamPointsToInfo>& paramPointsToMap = funcParamPointsToMap[func];
        
        if (paramPointsToMap.empty())  return;

        for (auto& paramPair : paramPointsToMap) {
            NodeID paramID = paramPair.first;
            ParamPointsToInfo& pointsToInfo = paramPair.second;

            std::string is_own = "Borrowed";
            std::pair<int, int> funcLineRange = getFuncLineRange(func);
            int funcLineStart = funcLineRange.first;
            int funcLineEnd = funcLineRange.second;

            bool is_free_operation = Is_freeOperation(paramID, func);
            std::cout << "is_free_operation: " << is_free_operation << std::endl;
            if (is_free_operation) is_own = "Owning";

            bool is_persistent = Is_persistent(paramID, func, funcLineStart, funcLineEnd);
            std::cout << "is_persistent: " << is_persistent << std::endl;
            if (is_persistent) is_own = "Owning";


            if (!is_free_operation && !is_persistent) {
                PTACallGraph* callgraph = pta->getPTACallGraph();
                ICFG* icfg = pag->getICFG();
                for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
                    ICFGNode* node = it->second;
                    if (node->getFun() != func) continue; 
                    if (CallICFGNode* callsite = SVFUtil::dyn_cast<CallICFGNode>(node)) {
                        const SVFInstruction* callInst = callsite->getCallSite(); 
                        const SVFFunction* callee = SVFUtil::getCallee(callInst); 

                        if (SVFUtil::isIntrinsicInst(callInst)) continue;

                        NodeID formalArgID = -1;
                        for (const SVFStmt* stmt : pag->getSVFStmtList(callsite)) {
                            std::cout << "stmt: " << stmt->toString() << std::endl;
                            
                            if (const CallPE* callPE = SVFUtil::dyn_cast<CallPE>(stmt)) {
                                NodeID actualArgID = callPE->getRHSVarID();
                                std::string _sameObject = isSameObject(actualArgID, func, true);
                                std::cout << "sameObject: " << _sameObject << std::endl;
                                if (_sameObject != "not_caller_param"){
                                    size_t colonPos = _sameObject.find(':');
                                    if(colonPos != std::string::npos){
                                        std::string extractedName = _sameObject.substr(0, colonPos);

                                        const PAGNode* paramNode = pag->getGNode(paramID);
                                        const SVFValue* val = paramNode->getValue();
                                        std::string currentParamName = val->getName();

                                        if (extractedName == currentParamName) {
                                            formalArgID = callPE->getLHSVarID(); 
                                            break;
                                        }

                                    }
                                }
                            }
                        }

                        if (formalArgID != -1) {
                            if (callee && !callee->isDeclaration() && funcParamPointsToMap.find(callee) != funcParamPointsToMap.end()) {
                                const std::map<NodeID, ParamPointsToInfo>& calleeParamInfo = funcParamPointsToMap[callee];
                                
                                auto calleeParamIt = calleeParamInfo.find(formalArgID);
                                if (calleeParamIt != calleeParamInfo.end()) {
                                    const ParamPointsToInfo& calleeParamData = calleeParamIt->second;
                                    
                                    if (calleeParamData.ownershipResult == "Owning") {
                                        is_own = "Owning";
                                    }
                                }
                            }
                        }

                    }
                }
            }


            pointsToInfo.ownershipResult = is_own;

           }
    }

    bool Is_freeOperation(NodeID paramID, const SVFFunction* func) {
        std::cout << "Checking if parameter with ID " << paramID << " is freed in function " << func->getName() << std::endl;
        
        const PAGNode* paramNode = pag->getGNode(paramID);
        if (!paramNode) return false;
        std::set<NodeID> relatedNodes;
        std::set<NodeID> bitcastNodes;  
        
        std::set<NodeID> visited;
        std::queue<NodeID> worklist;
        
        worklist.push(paramID);
        visited.insert(paramID);
        relatedNodes.insert(paramID);
        
        while (!worklist.empty()) {
            NodeID curID = worklist.front();
            worklist.pop();
            
            const PAGNode* curNode = pag->getGNode(curID);
            if (!curNode) continue;
            
            std::string nodeStr = curNode->toString();
            if (nodeStr.find("bitcast") != std::string::npos) {
                
                size_t eqPos = nodeStr.find("=");
                size_t dbgPos = nodeStr.find("!dbg");
                if (eqPos != std::string::npos && dbgPos != std::string::npos) {
                    std::string bitcastInst = nodeStr.substr(eqPos + 1, dbgPos - eqPos - 1);
                    bitcastInst = trim(bitcastInst);
                    // bitcastNodes[curID] = bitcastInst;
                    std::cout << "Found bitcast instruction: " << bitcastInst << std::endl;
                    
                    auto irPair = *irContents.begin(); 
                    const std::vector<std::string>& lines = irPair.second;
                    for (size_t i = 0; i < lines.size(); ++i) {
                        if (lines[i].find(bitcastInst) != std::string::npos) {
                            if (i + 1 < lines.size() && lines[i + 1].find("call void @free") != std::string::npos) {
                                std::cout << "Found free instruction: " << lines[i + 1] << std::endl;
                                return true;
                            }
                        }
                    }
                }
            }
            
            for (const PAGEdge* edge : curNode->getOutEdges()) {
                NodeID dstID = edge->getDstID();
                if (visited.find(dstID) != visited.end()) continue;

                std::string edgeTypeStr = getEdgeTypeStr(edge);
                if (edgeTypeStr == "GepObjPN" || edgeTypeStr == "GepValPN" || 
                    edge->getEdgeKind() == SVFStmt::Gep) {
                    continue;
                }

                const PAGNode* dstNode = pag->getGNode(dstID);
                relatedNodes.insert(dstID);
                worklist.push(dstID);
                visited.insert(dstID);
            }
        }

    return false;
    }
    

    bool Is_persistent(NodeID paramID, const SVFFunction* func, int funcLineStart, int funcLineEnd) {

        const PAGNode* paramNode = pag->getGNode(paramID);

        std::set<NodeID> relatedNodes;
        
        std::set<NodeID> visited;
        std::queue<NodeID> worklist;
        
        worklist.push(paramID);
        visited.insert(paramID);
        relatedNodes.insert(paramID);
        
        while (!worklist.empty()) {
            NodeID curID = worklist.front();
            worklist.pop();
            
            const PAGNode* curNode = pag->getGNode(curID);
            if (!curNode) continue;
            
            for (const PAGEdge* edge : curNode->getOutEdges()) {
                NodeID dstID = edge->getDstID();
                if (visited.find(dstID) != visited.end()) continue;
                
                std::string edgeTypeStr = getEdgeTypeStr(edge);
                if (edgeTypeStr == "GepObjPN" || edgeTypeStr == "GepValPN" || 
                    edge->getEdgeKind() == SVFStmt::Gep) {
                    continue;
                }

                const PAGNode* dstNode = pag->getGNode(dstID);
                NodeInfo dstNodeInfo = getNodeInfo(dstNode);
                int dstNodeLine = dstNodeInfo.line;
                if (dstNodeLine < funcLineStart || dstNodeLine > funcLineEnd) continue;

                relatedNodes.insert(dstID);
                worklist.push(dstID);
                visited.insert(dstID);
            }
        }


        ICFG* icfg = pag->getICFG();
        for (auto it = icfg->begin(), eit = icfg->end(); it != eit; ++it) {
            ICFGNode* icfgNode = it->second;            
            if (icfgNode->getFun() != func) continue;
            std::cout << "icfgNode: " << icfgNode->toString() << std::endl;


            for (const SVFStmt* stmt : pag->getSVFStmtList(icfgNode)) {
                if (const StoreStmt* store = SVFUtil::dyn_cast<StoreStmt>(stmt)) {
                    NodeID valueBeingStoredID = store->getRHSVarID(); 
                    NodeID destinationID = store->getLHSVarID(); 

                    if (relatedNodes.count(valueBeingStoredID)) {
                        const PAGNode* destNode = pag->getGNode(destinationID);
                        if (destNode) {
                            std::cout << "destNode: " << destNode->toString() << std::endl;
                            const MemObj* memObj = pag->getObject(destinationID);
                            if (memObj && memObj->isGlobalObj()) {
                                return true;
                            }

                            bool isStructField = false;
                            if (SVFUtil::isa<GepObjVar>(destNode)) {
                                isStructField = true;
                            }
                            else if (SVFUtil::isa<GepValVar>(destNode)) { 
                                isStructField = true;
                            }
                            else if (SVFUtil::isa<ValVar>(destNode)) {
                                std::string nodeStr = destNode->toString();
                                if (nodeStr.find("getelementptr") != std::string::npos) {
                                    if (nodeStr.find("struct") != std::string::npos || 
                                        (nodeStr.find("inbounds") != std::string::npos && 
                                         nodeStr.find("i32") != std::string::npos)) {
                                        isStructField = true;
                                    }
                                }
                            }

                            if (!isStructField && destNode->hasValue()) {
                                const SVFValue* val = destNode->getValue();
                                std::string valStr = val->toString();
                                if (valStr.find("getelementptr") != std::string::npos && 
                                    (valStr.find("struct") != std::string::npos || 
                                        valStr.find("field") != std::string::npos)) {
                                    isStructField = true;
                                }
                                
                            }

                            if (isStructField) {
                                return true;
                            }
                        }
                    }
                }
            }

            if (const CallICFGNode* callsite = SVFUtil::dyn_cast<CallICFGNode>(icfgNode)) {
                const SVFInstruction* callInst = callsite->getCallSite();
                if (callInst) {
                    const SVFFunction* callee = SVFUtil::getCallee(callInst);
                    if (callee && !callee->isDeclaration()) {
                        std::string calleeName = callee->getName();
                        
                        size_t scopePos = calleeName.rfind('_');
                        if (scopePos != std::string::npos && scopePos > 0) {
                            std::string prefix = calleeName.substr(0, scopePos);
                            std::string suffix = calleeName.substr(scopePos + 1);
                            static const std::set<std::string> containerPrefixes = {
                                "list", "array", "vec", "stack", "queue", "hash", 
                                "map", "tree", "set", "table", "buffer", "cache"
                            };
                            if (containerPrefixes.count(prefix)) {
                                calleeName = suffix; 
                            }
                        }

                        static const std::set<std::string> commonStructOps = {
                            "add", "insert", "append", "put", "push", "store", "save",
                            "add_head", "add_tail", "append_node", "insert_node",
                            "add_node", "insert_node", "add_child", "insert_child",
                            "add_entry", "insert_entry", "put_entry",
                            "enqueue", "push_front", "push_back"
                        };

                        bool isContainerOp = commonStructOps.count(calleeName);
                        
                        if (!isContainerOp) {
                            std::string fullName = callee->getName();
                            static const std::vector<std::string> containerPatterns = {
                                "_add_", "_insert_", "add_to_", "insert_to_", 
                                "_push_", "_append_", "_put_", "store_in_"
                            };
                            
                            for (const auto& pattern : containerPatterns) {
                                if (fullName.find(pattern) != std::string::npos) {
                                    isContainerOp = true;
                                    break;
                                }
                            }
                        }

                        if (isContainerOp) {
                            for (const SVFStmt* callSiteStmt : pag->getSVFStmtList(callsite)) {
                                if (const CallPE* callPE = SVFUtil::dyn_cast<CallPE>(callSiteStmt)) {
                                    NodeID actualArgID = callPE->getRHSVarID();

                                    if (relatedNodes.count(actualArgID)) {
                                        return true;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        return false;
        
    }

    std::string trim(const std::string& str) {
        size_t first = str.find_first_not_of(" \t\n\r");
        if (first == std::string::npos) return "";
        size_t last = str.find_last_not_of(" \t\n\r");
        return str.substr(first, last - first + 1);
    }


    void generateAnalysisReport(const std::string& outputFile) {
        nlohmann::json reportJson;
        
        auto now = std::chrono::system_clock::now();
        auto now_time_t = std::chrono::system_clock::to_time_t(now);
        std::string timestamp = std::ctime(&now_time_t);
        timestamp.pop_back(); 
        
        reportJson["timestamp"] = timestamp;
        reportJson["analysis_type"] = "Return Value Analysis";
        
        std::set<const SVFFunction*> allAnalyzedFunctions;
        
        for (const auto& funcPair : funcParamPointsToMap) {
            allAnalyzedFunctions.insert(funcPair.first);
        }
        
        for (const auto& funcPair : funcReturnPointsToMap) {
            allAnalyzedFunctions.insert(funcPair.first);
        }
        
        nlohmann::json functionsJson;
        
        for (const SVFFunction* func : allAnalyzedFunctions) {
            nlohmann::json funcJson;
            funcJson["function_name"] = func->getName();
            funcJson["is_declaration"] = func->isDeclaration();
            
            nlohmann::json paramsArrayJson = nlohmann::json::array();
            auto paramMapIt = funcParamPointsToMap.find(func);
            if (paramMapIt != funcParamPointsToMap.end()) {
                const std::map<NodeID, ParamPointsToInfo>& paramMap = paramMapIt->second;
                
                for (const auto& paramPair : paramMap) {
                    NodeID paramID = paramPair.first;
                    const ParamPointsToInfo& paramInfo = paramPair.second;
                    
                    nlohmann::json paramJson;
                    paramJson["param_id"] = paramID;
                    paramJson["param_name"] = paramInfo.paramName;
                    paramJson["mutability"] = paramInfo.mutabilityResult;
                    paramJson["nullability"] = paramInfo.nullabilityResult;
                    paramJson["ownership"] = paramInfo.ownershipResult;
                    
                    if (!paramInfo.structMemberUsage.empty()) {
                        nlohmann::json structMemberJson;
                        
                        if (paramInfo.structMemberUsage != "No struct members accessed") {
                            size_t colonPos = paramInfo.structMemberUsage.find(": {");
                            if (colonPos != std::string::npos) {
                                std::string structTypeName = paramInfo.structMemberUsage.substr(0, colonPos);
                                structMemberJson["struct_type"] = structTypeName;
                                size_t startPos = colonPos + 3; 
                                size_t endPos = paramInfo.structMemberUsage.find("}", startPos);
                                
                                if (endPos != std::string::npos) {
                                    std::string fieldsStr = paramInfo.structMemberUsage.substr(startPos, endPos - startPos);
                                    
                                    std::vector<std::string> fields;
                                    size_t pos = 0;
                                    std::string token;
                                    std::string delimiter = ", ";
                                    
                                    size_t lastPos = 0;
                                    while ((pos = fieldsStr.find(delimiter, lastPos)) != std::string::npos) {
                                        token = fieldsStr.substr(lastPos, pos - lastPos);
                                        token.erase(0, token.find_first_not_of(" "));
                                        token.erase(token.find_last_not_of(" ") + 1);
                                        fields.push_back(token);
                                        lastPos = pos + delimiter.length();
                                    }
                                    
                                    token = fieldsStr.substr(lastPos);
                                    if (!token.empty()) {
                                        token.erase(0, token.find_first_not_of(" "));
                                        token.erase(token.find_last_not_of(" ") + 1);
                                        fields.push_back(token);
                                    }
                                    
                                    nlohmann::json fieldsJson = nlohmann::json::array();
                                    for (const std::string& field : fields) {
                                        fieldsJson.push_back(field);
                                    }
                                    
                                    structMemberJson["accessed_fields"] = fieldsJson;
                                }
                            } else {
                                structMemberJson["raw_info"] = paramInfo.structMemberUsage;
                            }
                        } else {
                            structMemberJson["accessed_fields"] = nlohmann::json::array();
                        }
                        
                        paramJson["struct_member_usage"] = structMemberJson;
                    }
                    
                    nlohmann::json callsitesJson = nlohmann::json::array();
                    for (const auto& callsitePair : paramInfo.callStmts) {
                        const CallICFGNode* callsite = callsitePair.first;
                        const std::string& callStmt = callsitePair.second;
                        
                        nlohmann::json callsiteJson;
                        callsiteJson["call_stmt"] = callStmt;
                        
                        auto callerInfoIt = paramInfo.callerInfo.find(callsite);
                        if (callerInfoIt != paramInfo.callerInfo.end()) {
                            callsiteJson["caller_arg_id"] = callerInfoIt->second.first;
                            callsiteJson["same_object"] = callerInfoIt->second.second;
                        }
                        
                        auto pointsToInfoIt = paramInfo.pointsToInfo.find(callsite);
                        if (pointsToInfoIt != paramInfo.pointsToInfo.end()) {
                            callsiteJson["points_to_type"] = pointsToInfoIt->second.first;
                            callsiteJson["points_to"] = pointsToInfoIt->second.second;
                        }
                        
                        auto reversePathsIt = paramInfo.reversePaths.find(callsite);
                        if (reversePathsIt != paramInfo.reversePaths.end()) {
                            nlohmann::json reversePathsJson = processPathsToLocationArray(reversePathsIt->second);
                            if (!reversePathsJson.empty()) {
                                callsiteJson["reverse_paths"] = reversePathsJson;
                            }
                        }
                        
                        auto forwardPathsIt = paramInfo.forwardPaths.find(callsite);
                        if (forwardPathsIt != paramInfo.forwardPaths.end()) {
                            nlohmann::json forwardPathsJson = processPathsToLocationArray(forwardPathsIt->second);
                            if (!forwardPathsJson.empty()) {
                                callsiteJson["forward_paths"] = forwardPathsJson;
                            }
                        }
                        
                        callsitesJson.push_back(callsiteJson);
                    }
                    paramJson["callsites"] = callsitesJson;
                    
                    paramsArrayJson.push_back(paramJson);
                }
            }
            funcJson["parameters"] = paramsArrayJson;
            
            nlohmann::json returnsArrayJson = nlohmann::json::array();
            auto returnMapIt = funcReturnPointsToMap.find(func);
            if (returnMapIt != funcReturnPointsToMap.end()) {
                const std::map<NodeID, ReturnPointsToInfo>& returnMap = returnMapIt->second;
                
                for (const auto& returnPair : returnMap) {
                    NodeID returnID = returnPair.first;
                    const ReturnPointsToInfo& returnInfo = returnPair.second;
                    
                    nlohmann::json returnJson;
                    returnJson["return_id"] = returnID;
                    returnJson["return_name"] = returnInfo.returnName;
                    returnJson["mutability"] = returnInfo.mutabilityResult;
                    returnJson["nullability"] = returnInfo.nullabilityResult;
                    returnJson["ownership"] = returnInfo.ownershipResult;
                    returnJson["life_result"] = returnInfo.lifeResult;
                    
                    returnsArrayJson.push_back(returnJson);
                }
            }
            funcJson["returns"] = returnsArrayJson;
            
            functionsJson[func->getName()] = funcJson;
        }
        
        reportJson["function_analysis"] = functionsJson;
        
        std::ofstream outFile(outputFile);
        if (!outFile.is_open()) return;
        outFile << reportJson.dump(4) << std::endl;
        outFile.close();
    }



    nlohmann::json processPathsToLocationArray(const std::vector<std::vector<NodeID>>& paths) {
        nlohmann::json pathsArrayJson = nlohmann::json::array();
        
        for (const auto& path : paths) {
            if (path.empty()) continue;
            
            std::set<std::string> seenLocations;
            nlohmann::json pathJson = nlohmann::json::array();
            
            for (NodeID nodeId : path) {
                const PAGNode* node = pag->getGNode(nodeId);
                if (!node) continue;
                
                NodeInfo nodeInfo = getNodeInfo(node);
                
                std::string location;
                if (!nodeInfo.file_name.empty() && nodeInfo.line > 0) {
                    location = nodeInfo.file_name + ":" + std::to_string(nodeInfo.line);
                } else {
                    location = "unknown_location";
                }
                
                if (seenLocations.find(location) == seenLocations.end()) {
                    seenLocations.insert(location);
                    pathJson.push_back(location);
                }
            }
            
            if (!pathJson.empty()) {
                pathsArrayJson.push_back(pathJson);
            }
        }
        
        return pathsArrayJson;
    }

};



int main(int argc, char** argv) {
    std::cout << "SVF Pointer Analysis Start" << std::endl;
    

    std::vector<std::string> irFiles;
    for (int i = 1; i < argc; ++i) {
        irFiles.emplace_back(argv[i]);
    }
    
    for (const std::string& irFile : irFiles) {
        std::ifstream inFile(irFile);
        std::vector<std::string> lines;
        std::string line;
        while (std::getline(inFile, line)) {
            lines.push_back(line);
        }
        inFile.close();
        irContents[irFile] = lines;
    }

    std::cout << "Initializing SVF..." << std::endl;
    SVFModule* svfModule = LLVMModuleSet::getLLVMModuleSet()->buildSVFModule(irFiles);

    std::cout << "Building SVFIR..." << std::endl;
    SVFIRBuilder builder(svfModule);
    SVFIR* pag = builder.build();
    
    
    /// Create function parameter alias analysis client
    FunctionParamAliasAnalyzer* analyzer = new FunctionParamAliasAnalyzer(pag);
    
    /// Create context-sensitive pointer analysis
    std::cout << "Executing Context-Sensitive Pointer Analysis..." << std::endl;
    ContextDDA* pta = new ContextDDA(pag, analyzer);
    pta->initialize();
    
    /// Analyze function parameter alias relationships
    std::cout << "#######################################################" << std::endl;
    analyzer->startAnalysis_BottomUp(pta);
    
    std::string outputFile = "func_analysis_report.json";
    analyzer->generateAnalysisReport(outputFile);
    
    /// Cleanup remaining ca
    delete analyzer;
    delete pta;
    SVFIR::releaseSVFIR();
    LLVMModuleSet::releaseLLVMModuleSet();
    
    std::cout << "Analysis completed." << std::endl;
    return 0;
}